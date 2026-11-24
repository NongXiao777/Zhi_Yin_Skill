"""Select ERP product rows from a local file and preview packaging and price changes."""
import csv
import io
import json
import re
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from zipfile import BadZipFile, ZipFile


FILE_LIMIT = 10_000_000
COLUMNS = {
    'product_id': ('product_id', '产品编号', '商品编号'),
    'parent_sku': ('parent_sku', '父SKU', '父级SKU'),
    'sku': ('sku', '子SKU', '变体SKU', '商品SKU'),
    'variant': ('variant', '变体', '规格', '变体名称'),
    'title': ('title', '标题', '产品标题', '商品名称'),
    'description': ('description', '英文描述', '英文介绍'),
    'currency': ('currency', '币种', '货币'),
    'price': ('base_price', 'sale_price', '原售价', '售价', '销售价'),
    'weight': ('gross_weight_g', '毛重(克)', '毛重(g)', '包装毛重(克)', '包装重量(克)', '包装毛重'),
    'size': ('package_cm', '包装尺寸(cm)', '包装尺寸(厘米)'),
}
CURRENCIES = {'人民币': 'CNY', '美元': 'USD', '日元': 'JPY', '港币': 'HKD', '欧元': 'EUR', '英镑': 'GBP'}
NUMBER = r'([0-9]{1,12}(?:\.[0-9]{1,8})?)'
DESCRIBED_WEIGHT = re.compile(
    rf'^\s*(?:package\s+)?gross\s+weight\s*[:：]\s*{NUMBER}\s*(kg|g)\s*[.;]?\s*$', re.I | re.M)
DESCRIBED_SIZE = re.compile(
    rf'^\s*packag(?:e|ing)\s+(?:dimensions|size)\s*[:：]\s*{NUMBER}\s*[x×*]\s*{NUMBER}'
    rf'\s*[x×*]\s*{NUMBER}\s*(mm|cm|in|inch|inches)\s*[.;]?\s*$', re.I | re.M)
WEIGHT_UNITS = {'g': Decimal(1), 'kg': Decimal(1000)}
SIZE_UNITS = {'mm': Decimal('0.1'), 'cm': Decimal(1), 'in': Decimal('2.54'),
              'inch': Decimal('2.54'), 'inches': Decimal('2.54')}


class ProductError(ValueError):
    pass


def cell(value):
    return '' if value is None else str(value).strip()


def header_key(value):
    return cell(value).translate(str.maketrans('（）', '()')).casefold()


def text_file(path):
    raw = path.read_bytes()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('gb18030')


def table_records(rows):
    headers = [cell(value) for value in next(rows, ())]
    keys = [header_key(value) for value in headers if value]
    if len(keys) != len(set(keys)):
        raise ProductError('Product file contains duplicate column names')
    if not keys:
        raise ProductError('Product file needs a header row')
    for index, row in enumerate(rows, 2):
        if any(cell(value) for value in row[len(headers):]):
            raise ProductError(f'Product row {index} has values outside the named columns')
        record = {name: value for name, value in zip(headers, row) if name}
        if any(cell(value) for value in record.values()):
            yield index, record


def excel_records(path, sheet):
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError:
        raise ProductError('For XLSX, install openpyxl in this Python runtime or save the sheet as UTF-8 CSV') from None
    try:
        with ZipFile(path) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 70_000_000:
                raise ProductError('Uncompressed workbook exceeds the size limit')
        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except (BadZipFile, InvalidFileException, KeyError, ValueError) as error:
        if isinstance(error, ProductError):
            raise
        raise ProductError('Could not read the XLSX workbook') from None
    try:
        if sheet is not None and sheet not in book.sheetnames:
            raise ProductError('The specified XLSX sheet was not found')
        page = book[sheet] if sheet is not None else book.worksheets[0]
        if (page.max_column or 0) > 256:
            raise ProductError('The sheet exceeds 256 columns. Provide the product table only')
        yield from table_records(page.iter_rows(values_only=True))
    finally:
        book.close()


def input_records(path, sheet):
    if path.stat().st_size > FILE_LIMIT:
        raise ProductError('Product file exceeds the 10 MB size limit')
    suffix = path.suffix.lower()
    if suffix == '.xlsx':
        yield from excel_records(path, sheet)
    elif sheet is not None:
        raise ProductError('--sheet is available for XLSX files')
    elif suffix in ('.csv', '.tsv'):
        rows = csv.reader(io.StringIO(text_file(path), newline=''), delimiter='\t' if suffix == '.tsv' else ',')
        try:
            yield from table_records(rows)
        except csv.Error:
            raise ProductError('Could not read the delimited product table') from None
    elif suffix == '.json':
        data = json.loads(path.read_text(encoding='utf-8-sig'), parse_float=Decimal)
        if isinstance(data, dict):
            data = data.get('rows')
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProductError('Product JSON must contain an array of row objects')
        yield from enumerate(data, 1)
    else:
        raise ProductError('Use an XLSX, CSV, TSV or JSON product file')


def decimal_value(value):
    raw = cell(value)
    if not re.fullmatch(r'\+?[0-9]{1,12}(?:\.[0-9]{1,8})?', raw):
        raise ProductError('Use a nonnegative decimal with at most 12 whole digits and 8 decimal places')
    return Decimal(raw)


def positive_decimal(value):
    parsed = decimal_value(value)
    if parsed <= 0:
        raise ProductError('Value must be greater than zero')
    return parsed


def package_dimensions(value):
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = re.split(r'\s*[xX×*＊]\s*', cell(value))
    if len(parts) != 3:
        raise ProductError('Use package dimensions in length x width x height order')
    return [positive_decimal(part) for part in parts]


def currency_code(value):
    raw = cell(value)
    code = CURRENCIES.get(raw, raw.upper())
    if not re.fullmatch(r'[A-Z]{3}', code):
        raise ProductError('Use a three-letter currency code, such as CNY or USD')
    return code


def selected_rows(args):
    key = 'product_id' if args.product_id is not None else 'parent_sku'
    target = cell(getattr(args, key))
    if not target:
        raise ProductError('Provide a nonempty product ID or parent SKU')
    selected = []
    columns = set()
    price_column = header_key(args.price_column)
    aliases_by_field = {field: tuple(map(header_key, aliases)) for field, aliases in COLUMNS.items()}
    for index, row in input_records(args.file, args.sheet):
        normalized = {header_key(name): value for name, value in row.items()}
        if len(normalized) != len(row):
            raise ProductError('Product file contains duplicate column names after normalization')
        columns.update(normalized)
        values = {field: next((normalized[name] for name in aliases if cell(normalized.get(name))), None)
                  for field, aliases in aliases_by_field.items()}
        if cell(values[key]) != target:
            continue
        if args.price_column is not None:
            values['price'] = normalized.get(price_column)
        selected.append((index, values))
    if args.price_column is not None and price_column not in columns:
        raise ProductError('The specified price column was not found')
    if not selected:
        if not columns.intersection(aliases_by_field[key]):
            raise ProductError(f'The file needs a {key} column for this selector')
        raise ProductError('No product rows matched the requested ID or parent SKU')
    if key == 'parent_sku' and len({cell(values['product_id']) for _, values in selected if values['product_id']}) > 1:
        raise ProductError('That parent SKU matches multiple product IDs. Use --product-id')
    return {key: target}, selected


def parse_field(value, field, parser, issues):
    if not cell(value):
        issues.append(f'missing_{field}')
        return None
    try:
        return parser(value)
    except ProductError:
        issues.append(f'invalid_{field}')
        return None


def decimal_text(value):
    return format(value, 'f') if value is not None else None


def package_value(value, override, description, field, parser, pattern, units, issues):
    if override is not None:
        return override, 'override'
    if cell(value):
        return parse_field(value, field, parser, issues), 'column'
    try:
        matches = {
            tuple(positive_decimal(number) * units[unit.casefold()] for number in numbers)
            for *numbers, unit in pattern.findall(description)
        }
    except ProductError:
        issues.append(f'invalid_{field}_in_description')
        return None, None
    if len(matches) > 1:
        issues.append(f'conflicting_{field}_in_description')
        return None, None
    if matches:
        values = matches.pop()
        return (values[0] if len(values) == 1 else values), 'description'
    issues.append(f'missing_{field}')
    return None, None


def product_rows(selected, *, weight=None, size=None, currency=None, add=None, percent=None, decimals=2):
    skus = Counter(cell(values['sku']) for _, values in selected if cell(values['sku']))
    labels = Counter(cell(values['variant']) for _, values in selected if cell(values['variant']))
    quantizer = Decimal(1).scaleb(-decimals)
    for index, values in selected:
        issues = []
        sku, variant = cell(values['sku']), cell(values['variant'])
        if sku and skus[sku] > 1:
            issues.append('duplicate_sku')
        if not sku and len(selected) > 1 and (not variant or labels[variant] > 1):
            issues.append('ambiguous_variant')
        base = parse_field(values['price'], 'base_price', decimal_value, issues)
        description = cell(values['description'])
        mass, mass_source = package_value(values['weight'], weight, description, 'gross_weight_g', positive_decimal,
                                          DESCRIBED_WEIGHT, WEIGHT_UNITS, issues)
        dimensions, size_source = package_value(values['size'], size, description, 'package_cm', package_dimensions,
                                                DESCRIBED_SIZE, SIZE_UNITS, issues)
        code = parse_field(values['currency'] or currency, 'currency', currency_code, issues)
        if currency and code and currency != code:
            issues.append('currency_mismatch')
        result = {
            'source_row': index, 'product_id': cell(values['product_id']) or None,
            'parent_sku': cell(values['parent_sku']) or None, 'sku': sku or None, 'variant': variant or None,
            'title': cell(values['title'])[:160] or None, 'currency': code, 'base_price': decimal_text(base),
            'gross_weight_g': decimal_text(mass), 'package_cm': [decimal_text(d) for d in dimensions] if dimensions else None,
            'gross_weight_source': mass_source, 'package_size_source': size_source,
            'issues': issues,
        }
        if add is not None or percent is not None:
            proposed = None
            if base is not None and code and 'currency_mismatch' not in issues:
                adjusted = base + add if add is not None else base * (1 + percent / 100)
                proposed = adjusted.quantize(quantizer, rounding=ROUND_HALF_UP)
                if proposed <= 0:
                    issues.append('nonpositive_proposed_price')
            result['proposed_price'] = decimal_text(proposed)
        yield result


def product_result(args, *, preview=False):
    selection, selected = selected_rows(args)
    result = {'selection': selection, 'business_requests_sent': 0}
    options = {}
    if preview:
        add = positive_decimal(args.add_amount) if args.add_amount is not None else None
        percent = positive_decimal(args.markup_percent) if args.markup_percent is not None else None
        currency = currency_code(args.currency) if args.currency is not None else None
        if add is not None and currency is None:
            raise ProductError('--add-amount requires --currency')
        options = {
            'weight': positive_decimal(args.gross_weight_g) if args.gross_weight_g is not None else None,
            'size': package_dimensions(args.package_cm) if args.package_cm is not None else None,
            'currency': currency, 'add': add, 'percent': percent, 'decimals': args.decimals,
        }
        result.update(mode='preview', pricing={
            'rule': 'add_amount' if add is not None else 'markup_percent',
            'value': decimal_text(add if add is not None else percent), 'decimals': args.decimals,
            'currency': currency, 'price_column': args.price_column,
        })
    rows = list(product_rows(selected, **options))
    issue_counts = Counter(issue for row in rows for issue in row['issues'])
    result.update(total_variants=len(rows), issue_counts=dict(issue_counts))
    if preview:
        result['ready_for_review'] = not issue_counts
        if args.output is not None:
            document = json.dumps({**result, 'variants': rows}, ensure_ascii=False, indent=2) + '\n'
            if args.output.suffix.lower() != '.json':
                raise ProductError('Provide a .json output path')
            try:
                output = args.output.open('x', encoding='utf-8')
            except FileExistsError:
                raise ProductError('Output already exists. Choose a new preview file') from None
            try:
                with output:
                    output.write(document)
            except OSError:
                args.output.unlink(missing_ok=True)
                raise
            result['saved_to'] = str(args.output)
    return {**result, 'returned': min(len(rows), args.limit), 'variants': rows[:args.limit]}
