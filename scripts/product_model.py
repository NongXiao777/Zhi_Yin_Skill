"""Exact local product snapshots and minimal update plans; no network access."""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import unicodedata


class ProductDataError(ValueError):
    """The supplied product or requested change cannot be applied unambiguously."""


def _object_without_duplicates(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ProductDataError('Duplicate JSON property: ' + name)
        result[name] = value
    return result


def _invalid_constant(value):
    raise ProductDataError('Non-finite JSON number: ' + value)


def decode_json(text):
    """Decode JSON without passing monetary numbers through binary floats."""
    if not isinstance(text, str):
        raise ProductDataError('JSON input must be text')
    try:
        return json.loads(text, parse_float=Decimal,
                          object_pairs_hook=_object_without_duplicates,
                          parse_constant=_invalid_constant)
    except json.JSONDecodeError as error:
        raise ProductDataError('Invalid JSON at character %d' % error.pos) from error


def decimal_amount(value):
    """Validate a new surcharge against Decimal and the observed four-place writer."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ProductDataError('Money must be Decimal, an integer, or decimal text; floats are not accepted')
    if not isinstance(value, (Decimal, int, str)):
        raise ProductDataError('Money has an unsupported type')
    if isinstance(value, str) and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        raise ProductDataError('Money must be plain decimal text')
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ProductDataError('Invalid decimal amount') from error
    if not amount.is_finite():
        raise ProductDataError('Money must be finite')
    if not amount:
        return Decimal(0)
    # Trailing zeroes do not require rounding. Compare the actual nonzero scale.
    digits = amount.as_tuple().digits
    exponent = amount.as_tuple().exponent
    while digits and digits[-1] == 0 and exponent < 0:
        digits = digits[:-1]
        exponent += 1
    if exponent < -4:
        raise ProductDataError('Money exceeds the observed four-decimal encoding precision')
    if len(digits) + max(exponent, 0) > 29:
        raise ProductDataError('Money exceeds the .NET Decimal range')
    coefficient = int(''.join(str(digit) for digit in digits) or '0')
    if exponent > 0:
        coefficient *= 10 ** exponent
    if coefficient > 79228162514264337593543950335:
        raise ProductDataError('Money exceeds the .NET Decimal range')
    return amount


def _decimal_text(value, canonical=False):
    if not value.is_finite():
        raise ProductDataError('JSON numbers must be finite')
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if not value:
        text = '0'
    if not canonical and '.' not in text:
        text += '.0'
    return text


def encode_json(value, canonical=False):
    """Encode Decimal as JSON numbers, retaining unknown fields and array order."""
    if value is None or isinstance(value, (bool, str)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return _decimal_text(value, canonical)
    if isinstance(value, float):
        # Native Record columns can be Double. Preserve their shortest round-trip
        # representation; requested surcharges and parsed variant money remain Decimal.
        if not math.isfinite(value):
            raise ProductDataError('JSON numbers must be finite')
        return _decimal_text(Decimal(str(value)), True) if canonical else json.dumps(value)
    if isinstance(value, list):
        return '[' + ','.join(encode_json(item, canonical) for item in value) + ']'
    if isinstance(value, dict):
        if any(not isinstance(name, str) for name in value):
            raise ProductDataError('JSON property names must be strings')
        names = sorted(value) if canonical else value
        return '{' + ','.join(json.dumps(name, ensure_ascii=False) + ':' +
                              encode_json(value[name], canonical) for name in names) + '}'
    raise ProductDataError('Unsupported JSON value: ' + type(value).__name__)


def _language_map(value, field):
    if not isinstance(value, str):
        raise ProductDataError(field + ' must be a string column')
    if not value:
        return {}
    stripped = value.lstrip()
    if stripped.startswith(('{', '[')):
        languages = decode_json(value)
        if not isinstance(languages, dict):
            raise ProductDataError(field + ' must contain a language object')
    else:
        # Core.NMulti.Parse explicitly assigns legacy non-JSON text to zh.
        languages = {'zh': value}
    names = set()
    for language, text in languages.items():
        if not language or not isinstance(text, str):
            raise ProductDataError(field + ' contains an invalid language or text')
        if language.lower() in names:
            raise ProductDataError(field + ' contains duplicate case-insensitive language keys')
        names.add(language.lower())
    return languages


def _variant_money(variant):
    if 'money' in variant:
        amount = decimal_amount(variant['money'])
        if 'add' in variant and amount != decimal_amount(variant['add']):
            raise ProductDataError('Variant has conflicting money and legacy add values')
        return amount
    if 'add' in variant:
        return decimal_amount(variant['add'])
    # Core.NStock.Write omits a zero Money; a newly parsed NStock defaults to zero.
    return Decimal(0)


def _variants(value):
    if not isinstance(value, str):
        raise ProductDataError('sale_stock must be a string column')
    if not value:
        return []
    variants = decode_json(value)
    if not isinstance(variants, list):
        raise ProductDataError('sale_stock must contain an array')
    keys = set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise ProductDataError('Each variant must be an object')
        key = variant.get('key')
        if not isinstance(key, str) or not key:
            raise ProductDataError('Each variant must have a nonempty key')
        if key in keys:
            raise ProductDataError('Duplicate variant key: ' + key)
        keys.add(key)
        _variant_money(variant)
    return variants


@dataclass
class ProductSnapshot:
    product_id: int
    namespace: str
    record: dict
    variants: list
    titles: dict
    descriptions: dict


@dataclass
class MutationPlan:
    product_id: int
    namespace: str
    updates: dict
    restore_updates: dict
    base_fingerprint: str
    expected_record: dict
    changes: list

    def preview(self):
        return {'product_id': self.product_id, 'namespace': self.namespace,
                'changes': deepcopy(self.changes), 'fields': list(self.updates),
                'business_requests_sent': 0}


def parse_snapshot(response, product_id, namespace='sale'):
    if isinstance(product_id, bool) or not isinstance(product_id, int) or not 0 < product_id <= 2147483647:
        raise ProductDataError('Product id must be a positive Int32')
    if namespace not in ('sale', 'spider'):
        raise ProductDataError('Product namespace must be sale or spider')
    if isinstance(response, str):
        response = decode_json(response)
    if not isinstance(response, dict) or 'root' not in response:
        raise ProductDataError('Detail response must contain the root record')
    root = response['root']
    if isinstance(root, dict) and 'data' in root:
        root = root['data']
    if not isinstance(root, list) or len(root) != 1 or not isinstance(root[0], dict):
        raise ProductDataError('Detail response must contain exactly one root row')
    record = deepcopy(root[0])
    returned_id = record.get('sale_id')
    if isinstance(returned_id, bool) or returned_id != product_id:
        raise ProductDataError('Returned sale_id does not match the requested product')
    for field in ('sale_stock', 'sale_title', 'sale_intro'):
        if field not in record:
            raise ProductDataError('Detail response is missing ' + field)
    return ProductSnapshot(product_id, namespace, record, _variants(record['sale_stock']),
                           _language_map(record['sale_title'], 'sale_title'),
                           _language_map(record['sale_intro'], 'sale_intro'))


def _canonical_record(record):
    result = deepcopy(record)
    for field in ('sale_title', 'sale_intro'):
        result[field] = _language_map(result[field], field)
    variants = _variants(result['sale_stock'])
    for variant in variants:
        amount = _variant_money(variant)
        variant.pop('add', None)
        variant['money'] = amount
    result['sale_stock'] = variants
    return result


def fingerprint(snapshot):
    value = {'product_id': snapshot.product_id, 'namespace': snapshot.namespace,
             'record': _canonical_record(snapshot.record)}
    return hashlib.sha256(encode_json(value, canonical=True).encode('utf-8')).hexdigest()


def compact_summary(snapshot, variant_limit=10):
    if isinstance(variant_limit, bool) or not isinstance(variant_limit, int) or not 1 <= variant_limit <= 100:
        raise ProductDataError('Variant limit must be an integer from 1 to 100')
    return {'product_id': snapshot.product_id, 'namespace': snapshot.namespace,
            'titles': deepcopy(snapshot.titles),
            'description_languages': list(snapshot.descriptions),
            'description_lengths': {name: len(text) for name, text in snapshot.descriptions.items()},
            'currency': snapshot.record.get('sale_cur'),
            'cost': snapshot.record.get('sale_cost'),
            'distribution_price': snapshot.record.get('sale_price'),
            'weight_g': snapshot.record.get('sale_weight'),
            'size_cm': snapshot.record.get('sale_size'),
            'variant_count': len(snapshot.variants),
            'variants': [{'key': item['key'], 'sku': item.get('no'),
                          'surcharge': _decimal_text(_variant_money(item)),
                          'additional_weight_g': item.get('weight')}
                         for item in snapshot.variants[:variant_limit]],
            'fingerprint': fingerprint(snapshot)}


def plan_changes(snapshot, variant_key=None, new_money=None,
                 description_language=None, append_character=None):
    """Build explicit updates and exact rollback values without executing them."""
    updates = {'id': snapshot.product_id}
    restore = {'id': snapshot.product_id}
    expected = deepcopy(snapshot.record)
    changes = []
    if variant_key is not None or new_money is not None:
        if not isinstance(variant_key, str) or not variant_key or new_money is None:
            raise ProductDataError('A variant key and new money are required together')
        amount = decimal_amount(new_money)
        variants = deepcopy(snapshot.variants)
        matches = [item for item in variants if item['key'] == variant_key]
        if len(matches) != 1:
            raise ProductDataError('The requested variant key does not identify exactly one variant')
        selected = matches[0]
        original = _variant_money(selected)
        if original != amount:
            selected.pop('add', None)
            if amount:
                selected['money'] = amount
            else:
                selected.pop('money', None)
            encoded = encode_json(variants)
            updates['sale_stock'] = encoded
            restore['sale_stock'] = snapshot.record['sale_stock']
            expected['sale_stock'] = encoded
            changes.append({'field': 'sale_stock.money', 'variant_key': variant_key,
                            'before': _decimal_text(original), 'after': _decimal_text(amount)})
    if description_language is not None or append_character is not None:
        if not isinstance(description_language, str) or not description_language:
            raise ProductDataError('An explicit description language is required')
        if not isinstance(append_character, str) or len(append_character) != 1:
            raise ProductDataError('Append exactly one visible character')
        if not append_character.isprintable() or unicodedata.category(append_character)[0] in 'CMZ':
            raise ProductDataError('The appended character must be visible')
        descriptions = deepcopy(snapshot.descriptions)
        actual_language = next((name for name in descriptions
                                if name.lower() == description_language.lower()), description_language)
        original = descriptions.get(actual_language, '')
        changed = original + append_character
        descriptions[actual_language] = changed
        encoded = encode_json(descriptions)
        updates['sale_intro'] = encoded
        restore['sale_intro'] = snapshot.record['sale_intro']
        expected['sale_intro'] = encoded
        changes.append({'field': 'sale_intro', 'language': actual_language,
                        'before_length': len(original), 'after_length': len(changed),
                        'before_tail': original[-60:], 'after_tail': changed[-60:],
                        'appended': append_character})
    if not changes:
        raise ProductDataError('The requested plan makes no changes')
    return MutationPlan(snapshot.product_id, snapshot.namespace, updates, restore,
                        fingerprint(snapshot), expected, changes)


def assert_base_unchanged(snapshot, plan):
    if fingerprint(snapshot) != plan.base_fingerprint:
        raise ProductDataError('Product changed since the preview; rebuild the plan before saving')


def _diff_paths(left, right, path=''):
    if isinstance(left, dict) and isinstance(right, dict):
        paths = []
        for name in sorted(set(left) | set(right)):
            child = path + '.' + name if path else name
            if name not in left or name not in right:
                paths.append(child)
            else:
                paths.extend(_diff_paths(left[name], right[name], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [path + '.length']
        paths = []
        for index, (before, after) in enumerate(zip(left, right)):
            paths.extend(_diff_paths(before, after, '%s[%d]' % (path, index)))
        return paths
    return [] if left == right else [path]


def verify_readback(before, after, plan, ignored_fields=()):
    """Compare desired content with the server readback, including untouched fields."""
    if before.product_id != plan.product_id or before.namespace != plan.namespace:
        raise ProductDataError('Plan and original snapshot refer to different products')
    if after.product_id != plan.product_id or after.namespace != plan.namespace:
        raise ProductDataError('Readback refers to a different product')
    assert_base_unchanged(before, plan)
    wanted = _canonical_record(plan.expected_record)
    actual = _canonical_record(after.record)
    for field in ignored_fields:
        wanted.pop(field, None)
        actual.pop(field, None)
    differences = _diff_paths(wanted, actual)
    return {'verified': not differences, 'unexpected_fields': differences,
            'product_id': plan.product_id, 'changes': deepcopy(plan.changes)}


def verify_restore(original, restored, ignored_fields=()):
    if original.product_id != restored.product_id or original.namespace != restored.namespace:
        raise ProductDataError('Restored snapshot refers to a different product')
    expected = _canonical_record(original.record)
    actual = _canonical_record(restored.record)
    for field in ignored_fields:
        expected.pop(field, None)
        actual.pop(field, None)
    differences = _diff_paths(expected, actual)
    return {'restored': not differences, 'unexpected_fields': differences,
            'product_id': original.product_id}
