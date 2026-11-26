"""Read and edit a user-supplied collected-product JSON snapshot."""
import json
from collections import Counter
from decimal import Decimal, ROUND_FLOOR

from erp_products import FILE_LIMIT, ProductError, decimal_text, decimal_value, positive_decimal
from listing_copy import FIELDS, brand_issues, load_copy, words_only


PRODUCT_ID_MAX = 2_147_483_647
INTRO_LIMIT = 250_000
PRICE_ENDINGS = (Decimal('0.49'), Decimal('0.89'), Decimal('0.99'))
DESCRIPTION = 'product_description'
EXTRA_COPY_FIELDS = tuple(field for field in FIELDS if field != DESCRIPTION)
NATIVE_COPY_FIELDS = {
    'product_title': 'sale_title', 'product_highlight': 'sale_brief',
    'bullet_points': 'sale_bullet', 'backend_search_terms': 'sale_keys',
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def invalid_number(_):
    raise ValueError('Non-finite JSON number')


def decode_json(text):
    return json.loads(text, parse_float=Decimal, parse_constant=invalid_number, object_pairs_hook=unique_object)


def encode_json(value):
    # Keep precise decimal numbers in untouched fields and the complete stock array.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(f'{encode_json(key)}:{encode_json(item)}' for key, item in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(map(encode_json, value)) + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def product_number(value):
    text = str(value)
    if not text.isascii() or not text.isdecimal() or not 1 <= len(text) <= 10:
        raise ProductError('Use a positive Int32 collected-product number')
    number = int(text)
    if not 1 <= number <= PRODUCT_ID_MAX:
        raise ProductError('Use a positive Int32 collected-product number')
    return number


def read_snapshot(path, expected_id):
    if path.suffix.lower() != '.json' or path.stat().st_size > FILE_LIMIT:
        raise ProductError('Provide a collected-product JSON snapshot of at most 10 MB')
    try:
        snapshot = decode_json(path.read_text(encoding='utf-8-sig'))
    except (ValueError, RecursionError):
        raise ProductError('Invalid snapshot JSON or duplicate object keys') from None
    record = snapshot.get('root', snapshot) if isinstance(snapshot, dict) and 'sale_id' not in snapshot else snapshot
    if not isinstance(record, dict) or 'sale_id' not in record:
        raise ProductError('Snapshot must contain a sale_id at the top level or under root')
    if product_number(record['sale_id']) != expected_id:
        raise ProductError('The snapshot sale_id does not match --product-id')
    return snapshot, record


def collection(record, field, kind):
    raw = record.get(field)
    try:
        value = kind() if raw is None or raw == '' else decode_json(raw) if isinstance(raw, str) else raw
    except (ValueError, RecursionError):
        raise ProductError(f'Invalid {field} JSON or duplicate object keys') from None
    if not isinstance(value, kind):
        raise ProductError(f'{field} must contain a JSON {kind.__name__}')
    return value


def set_collection(record, field, value):
    original = record.get(field)
    record[field] = value if isinstance(original, type(value)) else encode_json(value)


def amount(value):
    if isinstance(value, Decimal):
        if value and (value.adjusted() > 11 or value.as_tuple().exponent < -8):
            raise ProductError('Amount exceeds 12 whole digits or 8 decimal places')
        value = decimal_text(value) if value else '0'
    text = str(value).strip()
    if text.startswith('-'):
        if text[1:].startswith('+'):
            raise ProductError('Use one sign for a surcharge adjustment')
        return -decimal_value(text[1:])
    return decimal_value(text)


def existing_surcharge(stock):
    return amount(stock.get('money', stock.get('add', 0)))


def variant_key(stock):
    key = stock.get('key')
    if key is not None and type(key) not in (str, int):
        raise ProductError('A variant key must be a string or integer')
    return str(key) if key is not None else ''


def channel_price(minimum):
    floor = minimum.to_integral_value(rounding=ROUND_FLOOR)
    return next((floor + ending for ending in PRICE_ENDINGS if floor + ending >= minimum),
                floor + 1 + PRICE_ENDINGS[0])


def intro_text(path, blocked_brands):
    if path.stat().st_size > INTRO_LIMIT:
        raise ProductError('Introduction file exceeds 250 KB')
    try:
        text = path.read_text(encoding='utf-8-sig').strip()
    except UnicodeDecodeError:
        raise ProductError('Provide a UTF-8 introduction file') from None
    if not text:
        raise ProductError('Introduction file is empty')
    blocked = {words_only(brand) for brand in blocked_brands} - {''}
    issues = brand_issues(text, blocked)
    if issues:
        raise ProductError('English introduction failed checks: ' + ', '.join(issues))
    return text


def appended_intro(existing, suffix, blocked_brands):
    if not isinstance(existing, str) or not existing.strip():
        raise ProductError('An existing nonempty English introduction is required for --append-intro')
    if not isinstance(suffix, str) or not suffix or '\0' in suffix:
        raise ProductError('Provide nonempty text without null characters for --append-intro')
    text = existing + suffix
    if len(text.encode('utf-8')) > INTRO_LIMIT:
        raise ProductError('Appended English introduction exceeds 250 KB')
    blocked = {words_only(brand) for brand in blocked_brands} - {''}
    issues = brand_issues(text, blocked)
    if issues:
        raise ProductError('English introduction failed checks: ' + ', '.join(issues))
    return text


def copy_updates(path, blocked_brands):
    copy, source_brands, status = load_copy(path, partial=True)
    if status == 'HOLD':
        raise ProductError('Listing copy is on HOLD')
    blocked = {words_only(brand) for brand in [*source_brands, *blocked_brands]} - {''}
    updates = {}
    for field, raw in copy.items():
        lines = raw if field == 'bullet_points' else [raw]
        if field != 'backend_search_terms' and (not lines or any(not line for line in lines)):
            raise ProductError(f'{field} must contain nonempty text')
        text = '\n'.join(lines)
        issues = brand_issues(text, blocked)
        if issues:
            raise ProductError(f'{field} failed checks: ' + ', '.join(issues))
        updates[field] = text
    return updates


def copy_locales(record):
    copy = collection(record, 'listing_copy', dict)
    copy = dict(copy)
    for field, native in NATIVE_COPY_FIELDS.items():
        if native in record:
            copy[field] = collection(record, native, dict)
    for field in EXTRA_COPY_FIELDS:
        if field in copy:
            locales = copy[field]
            if not isinstance(locales, dict) or any(not isinstance(value, str) for value in locales.values()):
                raise ProductError(f'{field} must map languages to text')
    return copy


def save_snapshot(path, snapshot, product_id):
    if path.suffix.lower() != '.json':
        raise ProductError('Choose a .json output file')
    content = (encode_json(snapshot) + '\n').encode('utf-8')
    if len(content) > FILE_LIMIT:
        raise ProductError('Edited snapshot exceeds 10 MB')
    try:
        handle = path.open('xb')
    except FileExistsError:
        raise ProductError('Output already exists. Choose a new snapshot file') from None
    try:
        with handle:
            handle.write(content)
        read_back, _ = read_snapshot(path, product_id)
        if read_back != snapshot:
            raise ProductError('Saved snapshot did not match the edits on read-back')
    except (OSError, ProductError):
        path.unlink(missing_ok=True)
        raise


def collected_result(args, *, edit=False):
    product_id = product_number(args.product_id)
    snapshot, record = read_snapshot(args.file, product_id)
    result = record_result(args, product_id, record, edit=edit)
    result.update(mode='local_snapshot', business_requests_sent=0)
    if edit and args.output is not None:
        save_snapshot(args.output, snapshot, product_id)
        result.update(saved_to=str(args.output), local_read_back_verified=True)
    return result


def record_result(args, product_id, record, *, edit=False, live=False):
    stock = collection(record, 'sale_stock', list)
    intro = collection(record, 'sale_intro', dict)
    if any(not isinstance(item, dict) for item in stock):
        raise ProductError('sale_stock must contain variant objects')
    if any(not isinstance(text, str) for text in intro.values()):
        raise ProductError('sale_intro must map languages to text')
    keys = [variant_key(item) for item in stock]
    surcharges = [existing_surcharge(item) for item in stock]
    result = {'product_id': product_id, 'sale_cur': record.get('sale_cur'), 'sale_weight': record.get('sale_weight'),
              'sale_size': record.get('sale_size'), 'total_variants': len(stock)}
    for field in ('sale_cost', 'sale_price'):
        value = record.get(field)
        result[field] = decimal_text(amount(value)) if value is not None and value != '' else None

    translations = copy_locales(record) if args.include_copy or (edit and args.copy_file is not None) else {}
    if edit:
        updates = copy_updates(args.copy_file, args.blocked_brand) if args.copy_file is not None else {}
        if args.intro_file is not None:
            if DESCRIPTION in updates:
                raise ProductError('Supply the English description through one option')
            updates[DESCRIPTION] = intro_text(args.intro_file, args.blocked_brand)
        append = getattr(args, 'append_intro', None)
        if append is not None:
            if DESCRIPTION in updates:
                raise ProductError('Supply the English description through one option')
            updates[DESCRIPTION] = appended_intro(intro.get('en'), append, args.blocked_brand)
        edits = [(key, value, False) for key, value in args.set_surcharge]
        edits.extend((key, value, True) for key, value in args.adjust_surcharge)
        if not edits and not updates and args.minimum_channel_price is None:
            raise ProductError('Provide a surcharge, copy to update or a minimum channel price')
        if len({key for key, _, _ in edits}) != len(edits):
            raise ProductError('Specify each variant key at most once per edit')
        counts = Counter(keys)
        changes = []
        for key, value, adjust in edits:
            if not key or counts[key] != 1:
                raise ProductError(f'Variant key must match exactly one row: {key!r}')
            index = keys.index(key)
            old_value = surcharges[index]
            new_value = decimal_value(decimal_text(old_value + amount(value))) if adjust else decimal_value(value)
            if old_value == new_value:
                continue
            item = stock[index]
            item.pop('add', None)
            if new_value:
                item['money'] = new_value
            else:
                item.pop('money', None)
            surcharges[index] = new_value
            changes.append({'key': key, 'old_money': decimal_text(old_value), 'new_money': decimal_text(new_value)})
        if changes:
            set_collection(record, 'sale_stock', stock)
        result['variant_changes'] = changes

        if DESCRIPTION in updates:
            text = updates.pop(DESCRIPTION)
            result['intro_changed'] = text != intro.get('en')
            if result['intro_changed']:
                intro['en'] = text
                set_collection(record, 'sale_intro', intro)

        if live and updates.keys() - translations.keys():
            missing = ', '.join(sorted(updates.keys() - translations.keys()))
            raise ProductError(f'The live transport did not expose these listing fields: {missing}')
        copy_changes = [field for field, text in updates.items() if translations.get(field, {}).get('en') != text]
        for field in copy_changes:
            translations.setdefault(field, {})['en'] = updates[field]
        if copy_changes:
            legacy = collection(record, 'listing_copy', dict)
            for field in copy_changes:
                native = NATIVE_COPY_FIELDS[field]
                if native in record or field not in legacy:
                    set_collection(record, native, translations[field])
                else:
                    legacy[field] = translations[field]
                    set_collection(record, 'listing_copy', legacy)
        if args.copy_file is not None:
            result['copy_fields_changed'] = copy_changes + ([DESCRIPTION] if result.get('intro_changed') else [])
        if args.minimum_channel_price is not None:
            minimum = positive_decimal(args.minimum_channel_price)
            result['channel_price_quote'] = {
                'minimum': decimal_text(minimum), 'price': decimal_text(channel_price(minimum)),
            }

    result['intro_en_characters'] = len(intro.get('en', ''))
    if args.include_intro:
        result['intro_en'] = intro.get('en')
    if args.include_copy:
        result['copy_en'] = {field: translations[field].get('en') for field in EXTRA_COPY_FIELDS if field in translations}
        result['copy_en'][DESCRIPTION] = intro.get('en')
    result['returned'] = min(len(stock), args.limit)
    result['variants'] = [
        {'key': key or None, 'no': item.get('no'), 'spec': item.get('spec'), 'money': decimal_text(surcharge)}
        for key, item, surcharge in zip(keys[:args.limit], stock, surcharges)
    ]
    return result
