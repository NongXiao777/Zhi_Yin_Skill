"""Persist, apply once and selectively restore product edits over the verified transport.

The saved intent, process lock and recoverable state follow PR #3's useful design;
all business requests use the existing vendor transport and protected sessions.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os
import tempfile

from collected_products import (EXTRA_COPY_FIELDS, collection, decode_json, encode_json, existing_surcharge,
                                product_number, record_result, set_collection, variant_key)
from collected_transport import EDIT_FIELDS, ClientReloginRequired, TransportConflict, detail, request
from erp_products import FILE_LIMIT, ProductError, decimal_text


KIND = 'zhiying-product-plan'


def _read_document(path):
    path = Path(path).resolve()
    if path.stat().st_size > FILE_LIMIT:
        raise ProductError('Product plan exceeds 10 MB')
    try:
        value = decode_json(path.read_text(encoding='utf-8-sig'))
    except (ValueError, RecursionError, UnicodeError):
        raise ProductError('Invalid product plan JSON') from None
    if not isinstance(value, dict):
        raise ProductError('Product plan must be a JSON object')
    return value


def _write_document(path, value, *, create=False):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (encode_json(value) + '\n').encode('utf-8')
    if len(data) > FILE_LIMIT:
        raise ProductError('Product plan exceeds 10 MB')
    if create:
        try:
            with path.open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            raise ProductError('Plan already exists; choose a new path') from None
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.plan-', delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _plan_lock(path):
    path = Path(path).resolve()
    with path.with_name(path.name + '.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ProductError('Another process is using this plan') from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProductError('Another process is using this plan') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stock_map(record):
    stock = collection(record, 'sale_stock', list)
    result = {}
    for row in stock:
        if not isinstance(row, dict) or not variant_key(row) or variant_key(row) in result:
            raise ProductError('Plans require unique nonempty variant keys')
        if 'money' in row and 'add' in row and existing_surcharge(row) != existing_surcharge({'money': row['add']}):
            raise ProductError('Variant has conflicting money and legacy add values')
        result[variant_key(row)] = row
    return stock, result


def _semantic(record, field):
    value = deepcopy(collection(record, field, EDIT_FIELDS[field]))
    if field == 'sale_stock':
        _stock_map(record)
        for row in value:
            money = existing_surcharge(row)
            row.pop('money', None)
            row.pop('add', None)
            row['money'] = money
    else:
        maps = value.values() if field == 'listing_copy' else (value,)
        if any(not isinstance(languages, dict) or any(not isinstance(name, str) or not name or not isinstance(text, str)
                                                      for name, text in languages.items()) for languages in maps):
            raise ProductError('Plan copy must map languages to text')
    return value


def _changes(before, after):
    changes = []
    for field in sorted(set(before) | set(after)):
        if before.get(field) == after.get(field):
            continue
        if field not in EDIT_FIELDS:
            raise ProductError('Plan changes an unsupported field: ' + field)
        if _semantic(before, field) == _semantic(after, field):
            continue
        if field == 'sale_stock':
            old_rows, old = _stock_map(before)
            new_rows, new = _stock_map(after)
            if [variant_key(row) for row in old_rows] != [variant_key(row) for row in new_rows]:
                raise ProductError('Plan changes variant identities or order')
            for key in old:
                left = {k: v for k, v in old[key].items() if k not in ('money', 'add')}
                right = {k: v for k, v in new[key].items() if k not in ('money', 'add')}
                if left != right:
                    raise ProductError('Plan changes a variant field other than surcharge: ' + key)
                old_money, new_money = existing_surcharge(old[key]), existing_surcharge(new[key])
                if old_money != new_money:
                    changes.append({'field': field, 'variant_key': key,
                                    'before': decimal_text(old_money), 'after': decimal_text(new_money)})
        else:
            old, new = _semantic(before, field), _semantic(after, field)
            if field == 'listing_copy':
                names = sorted(set(old) | set(new))
                if any(name not in EXTRA_COPY_FIELDS and old.get(name) != new.get(name) for name in names):
                    raise ProductError('Plan changes an unsupported listing copy field')
                if any(not isinstance(old.get(name, {}), dict) or not isinstance(new.get(name, {}), dict) for name in names):
                    raise ProductError('Listing copy plan must contain language maps')
                maps = [(name, old.get(name, {}), new.get(name, {})) for name in names]
            else:
                maps = [(None, old, new)]
            for copy_field, left, right in maps:
                for language in sorted(set(left) | set(right)):
                    if any(not isinstance(v, str) for v in (left.get(language, ''), right.get(language, ''))):
                        raise ProductError('Plan language values must be text')
                    if left.get(language) != right.get(language):
                        if language != 'en':
                            raise ProductError('Product plans support English copy edits only')
                        change = {'field': field, 'language': language,
                                  'before': left.get(language), 'after': right.get(language)}
                        if copy_field is not None:
                            change['copy_field'] = copy_field
                        changes.append(change)
    if not changes:
        raise ProductError('The plan makes no changes')
    return changes


def _load_plan(path):
    document = _read_document(path)
    if document.get('format') != 1 or document.get('kind') != KIND:
        raise ProductError('Unsupported product plan format')
    try:
        number = product_number(document['product_id'])
        if document['namespace'] not in ('sale', 'spider'):
            raise ProductError('Product namespace must be sale or spider')
        before, expected = document['original_record'], document['expected_record']
        if not isinstance(before, dict) or not isinstance(expected, dict):
            raise ProductError('Plan snapshots must be objects')
        if product_number(before['sale_id']) != number or product_number(expected['sale_id']) != number:
            raise ProductError('Plan snapshots target another product')
        for record in (before, expected):
            _stock_map(record)
            for field in EDIT_FIELDS:
                if field in record:
                    _semantic(record, field)
        actual = _changes(before, expected)
        if document['changes'] != actual:
            raise ProductError('Plan preview does not match its actual changes')
        if document['state'] not in ('prepared', 'write_attempted', 'applied', 'verification_failed',
                                      'restore_attempted', 'restore_verification_failed', 'restored'):
            raise ProductError('Unknown product plan state')
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ProductError('Product plan is incomplete or invalid') from None
    return document


def _summary(document):
    changes = []
    for change in document['changes']:
        item = deepcopy(change)
        if 'language' in item:
            old, new = item.pop('before'), item.pop('after')
            item.update(before_characters=len(old or ''), after_characters=len(new or ''),
                        before_tail=(old or '')[-60:], after_tail=(new or '')[-60:])
        changes.append(item)
    return {'ok': True, 'state': document['state'], 'product_id': document['product_id'],
            'namespace': document['namespace'], 'changes': changes}


def inspect_plan(path):
    return _summary(_load_plan(path))


def create_plan(transport, product_id, namespace, edit_args, path):
    number = product_number(product_id)
    if namespace not in ('sale', 'spider'):
        raise ProductError('Product namespace must be sale or spider')
    if Path(path).exists():
        raise ProductError('Plan already exists; choose a new path')
    if isinstance(edit_args, dict):
        allowed = {'set_surcharge', 'adjust_surcharge', 'append_intro'}
        if edit_args.keys() - allowed:
            raise ProductError('Unknown plan instruction fields')
        edit_args = SimpleNamespace(include_copy=False, include_intro=False, limit=2,
            copy_file=None, intro_file=None, blocked_brand=[], minimum_channel_price=None,
            append_intro=edit_args.get('append_intro'), set_surcharge=edit_args.get('set_surcharge', []),
            adjust_surcharge=edit_args.get('adjust_surcharge', []))
    before = detail(transport, number, namespace + '.detail')
    expected = deepcopy(before)
    record_result(edit_args, number, expected, edit=True, live=True)
    document = {'format': 1, 'kind': KIND, 'state': 'prepared', 'product_id': number,
                'namespace': namespace, 'original_record': before, 'expected_record': expected,
                'changes': _changes(before, expected)}
    _write_document(path, document, create=True)
    return {**_summary(document), 'plan_file': str(Path(path).resolve()), 'update_sent': False}


def _same_target(record, change, target):
    field = change['field']
    if field == 'sale_stock':
        _, rows = _stock_map(record)
        row = rows.get(change['variant_key'])
        return row is not None and existing_surcharge(row) == existing_surcharge({'money': change[target]})
    values = collection(record, field, dict)
    if 'copy_field' in change:
        values = values.get(change['copy_field'], {})
    return values.get(change['language']) == change[target]


def _restore_draft(current, document):
    draft = deepcopy(current)
    originals = _stock_map(document['original_record'])[1] if any(c['field'] == 'sale_stock' for c in document['changes']) else {}
    for change in document['changes']:
        if _same_target(current, change, 'before'):
            continue
        if not _same_target(current, change, 'after'):
            raise ProductError('A target was changed after the plan; restoration stopped')
        field = change['field']
        if field == 'sale_stock':
            rows, mapped = _stock_map(draft)
            row = mapped[change['variant_key']]
            for key in ('money', 'add'):
                row.pop(key, None)
            row.update({key: originals[change['variant_key']][key] for key in ('money', 'add')
                        if key in originals[change['variant_key']]})
            set_collection(draft, field, rows)
        else:
            values = collection(draft, field, dict)
            languages = values.setdefault(change['copy_field'], {}) if 'copy_field' in change else values
            if change['before'] is None:
                languages.pop(change['language'], None)
            else:
                languages[change['language']] = change['before']
            if 'copy_field' in change and not languages and change['copy_field'] not in collection(document['original_record'], field, dict):
                values.pop(change['copy_field'], None)
            set_collection(draft, field, values)
    return draft


def _verify(current, after, wanted, document, target):
    target_matches = all(_same_target(after, change, target) for change in document['changes'])
    fields = {change['field'] for change in document['changes']}
    content_matches = all(_semantic(after, field) == _semantic(wanted, field) for field in fields)
    others = sorted(field for field in set(current) | set(after)
                    if field not in fields and current.get(field) != after.get(field))
    return {'verified': target_matches and content_matches, 'target_matches': target_matches,
            'edited_columns_match': content_matches, 'other_changed_fields': others}


def _send_and_verify(transport, path, document, current, wanted, *, restoring=False):
    fields = {field: wanted[field] for field in {c['field'] for c in document['changes']}
              if _semantic(current, field) != _semantic(wanted, field)}
    if not fields:
        document['state'] = 'restored' if restoring else 'applied'
        _write_document(path, document)
        return {**_summary(document), 'update_sent': False, 'remote_read_back_verified': True}
    previous_state = document['state']
    document['state'] = 'restore_attempted' if restoring else 'write_attempted'
    _write_document(path, document)
    try:
        request(transport, {'command': document['namespace'] + '.update', 'id': document['product_id'],
                            'fields': fields, 'expected': {field: current.get(field) for field in fields}})
    except ClientReloginRequired:
        # The transport rejected the session before making any business request.
        document['state'] = previous_state
        _write_document(path, document)
        raise
    except TransportConflict:
        # The transport confirms no update was sent for a baseline conflict.
        document['state'] = 'verification_failed' if restoring else 'prepared'
        _write_document(path, document)
        raise
    except ProductError:
        raise ProductError('Write outcome is unverified. Inspect this plan before another write.') from None
    try:
        after = detail(transport, document['product_id'], document['namespace'] + '.detail')
    except ProductError:
        raise ProductError('Write was acknowledged, but read-back failed. Inspect this plan before another write.') from None
    verification = _verify(current, after, wanted, document, 'before' if restoring else 'after')
    document['state'] = ('restored' if restoring else 'applied') if verification['verified'] else (
        'restore_verification_failed' if restoring else 'verification_failed')
    document['verification'] = verification
    _write_document(path, document)
    return {**_summary(document), 'ok': verification['verified'], 'update_sent': True,
            'remote_read_back_verified': verification['verified'], 'verification': verification}


def apply_plan(transport, path):
    with _plan_lock(path):
        document = _load_plan(path)
        if document['state'] != 'prepared':
            raise ProductError('Plan already attempted. Inspect or restore it; do not replay it.')
        current = detail(transport, document['product_id'], document['namespace'] + '.detail')
        for field in {c['field'] for c in document['changes']}:
            if _semantic(current, field) != _semantic(document['original_record'], field):
                raise ProductError('Edited column changed since the plan; prepare a new plan')
        wanted = deepcopy(current)
        for field in {c['field'] for c in document['changes']}:
            wanted[field] = document['expected_record'][field]
        return _send_and_verify(transport, path, document, current, wanted)


def restore_plan(transport, path):
    with _plan_lock(path):
        document = _load_plan(path)
        if document['state'] == 'prepared':
            raise ProductError('This plan has no write to restore')
        if document['state'] == 'restored':
            return {**_summary(document), 'update_sent': False, 'previous_read_back_verified': True}
        current = detail(transport, document['product_id'], document['namespace'] + '.detail')
        wanted = _restore_draft(current, document)
        return _send_and_verify(transport, path, document, current, wanted, restoring=True)
