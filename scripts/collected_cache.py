"""Read product responses from the embedded browser's Chromium blockfile cache."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
import re
import struct
from urllib.parse import parse_qs, urlsplit, urlunsplit
import zlib

from erp_products import ProductError


INDEX_HEADER = 368
BLOCK_HEADER = 8192
BLOCK_SIZES = {2: 256, 3: 1024, 4: 4096}
MAX_STREAM = 8_000_000
MAX_KEY = 128_000
MAX_INDEX_SLOTS = 1_048_576
WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
PDP_PATH = '/h5/mtop.aliexpress.pdp.pc.query/'
DESCRIPTION_PATH = '/product/description/pc/'
ID_PATTERN = re.compile(r'[0-9]{1,24}')
ENTRY_METADATA = struct.Struct('<II12xiQiI4i4I')

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _create_file = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
    _create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _create_file.restype = wintypes.HANDLE


def open_cache_file(path):
    if os.name != 'nt':
        return path.open('rb')
    # CEF keeps the block files open for writing. Share reads, writes and deletion.
    handle = _create_file(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), 'rb')


class BlockCache:
    def __init__(self, root, stack):
        self.root = root
        self.stack = stack
        self.blocks = {}

    def read(self, address, size):
        if not address & 0x80000000 or not 0 < size <= MAX_STREAM:
            return b''
        kind = (address >> 28) & 7
        try:
            if kind == 0:
                with open_cache_file(self.root / f'f_{address & 0x0fffffff:06x}') as stream:
                    data = stream.read(size)
            elif kind in BLOCK_SIZES:
                block = BLOCK_SIZES[kind]
                if size > block * (((address >> 24) & 3) + 1):
                    return b''
                file_no = (address >> 16) & 0xff
                if file_no not in self.blocks:
                    stream = self.stack.enter_context(open_cache_file(self.root / f'data_{file_no}'))
                    header = stream.read(16)
                    self.blocks[file_no] = (None, None)
                    if len(header) == 16:
                        magic, _, number, _, entry_size = struct.unpack('<IIhhi', header)
                        if magic == 0xC104CAC3 and number == file_no:
                            self.blocks[file_no] = (stream, entry_size)
                stream, entry_size = self.blocks[file_no]
                if stream is None or block != entry_size:
                    return b''
                stream.seek(BLOCK_HEADER + (address & 0xffff) * block)
                data = stream.read(size)
            else:
                return b''
        except OSError:
            return b''
        return data if len(data) == size else b''

    def entries(self):
        try:
            with open_cache_file(self.root / 'index') as stream:
                data = stream.read(INDEX_HEADER + 4 * MAX_INDEX_SLOTS + 1)
        except OSError:
            raise ProductError('The embedded browser cache index could not be read. Check --app.') from None
        if len(data) < INDEX_HEADER:
            raise ProductError('The embedded browser cache index is incomplete.')
        magic, version = struct.unpack_from('<II', data)
        slots = struct.unpack_from('<i', data, 28)[0] or 65_536
        if (magic != 0xC103CAC3 or version not in (0x20000, 0x20001, 0x30000) or
                not 0 < slots <= MAX_INDEX_SLOTS or len(data) != INDEX_HEADER + slots * 4):
            raise ProductError('Unsupported Chromium blockfile cache index format.')

        visited = set()
        for (address,) in struct.iter_unpack('<I', memoryview(data)[INDEX_HEADER:]):
            while address and address not in visited:
                if len(visited) >= 100_000:
                    raise ProductError('The embedded browser cache exceeds the inspection limit.')
                visited.add(address)
                if (address >> 28) & 7 != 2:
                    break
                record = self.read(address, 256)
                if not record:
                    break
                _, next_address, state, created, key_size, long_key, *streams = ENTRY_METADATA.unpack_from(record)
                if state == 0 and 0 < key_size <= MAX_KEY:
                    key = self.read(long_key, key_size) if long_key else self.read(address, 96 + key_size)[96:]
                    url = cache_url(key)
                    if url is not None:
                        header_size, body_size = streams[:2]
                        header_address, body_address = streams[4:6]
                        if body_size:
                            yield url, created, header_address, header_size, body_address, body_size
                address = next_address

    def body(self, entry):
        _, _, header_address, header_size, body_address, body_size = entry
        body = self.read(body_address, body_size)
        if not body:
            return b''
        header = self.read(header_address, header_size)
        encoding = re.search(rb'(?:^|[\x00\r\n])content-encoding:\s*([a-z0-9-]+)', header, re.I)
        codec = encoding[1].lower() if encoding else b'identity'
        if body.startswith(b'\x1f\x8b') or codec in (b'gzip', b'deflate'):
            wbits = 31 if body.startswith(b'\x1f\x8b') or codec == b'gzip' else 15
            try:
                decoder = zlib.decompressobj(wbits)
                expanded = decoder.decompress(body, MAX_STREAM + 1)
                return expanded if decoder.eof and len(expanded) <= MAX_STREAM else b''
            except zlib.error:
                return b''
        return body if codec == b'identity' else b''


def cache_url(key):
    # A Chromium partition prefix can precede the actual request URL.
    suffix = key.rsplit(b' ', 1)[-1]
    start = suffix.find(b'https://')
    if start < 0:
        return None
    try:
        parts = urlsplit(suffix[start:].decode('utf-8'))
        if parts.username or parts.password or parts.port not in (None, 443):
            return None
    except (ValueError, UnicodeError):
        return None
    if ((parts.hostname == 'acs.aliexpress.com' and parts.path.startswith(PDP_PATH)) or
            (parts.hostname == 'pdp.aliexpress-media.com' and parts.path.startswith(DESCRIPTION_PATH))):
        return parts
    return None


def as_object(value):
    return value if isinstance(value, dict) else {}


def as_objects(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def public_text(value, limit=2000):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def product_id(value):
    if type(value) is int:
        value = str(value)
    return value if isinstance(value, str) and ID_PATTERN.fullmatch(value) else None


def image_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit('https:' + value if value.startswith('//') else value)
        host = url.hostname or ''
        if (url.scheme == 'https' and not url.username and not url.password and url.port in (None, 443)
                and host.endswith(('.alicdn.com', '.aliexpress-media.com'))):
            return urlunsplit(('https', host, url.path, '', ''))
    except ValueError:
        pass
    return None


def description_key(url):
    if (url is None or url.hostname != 'pdp.aliexpress-media.com' or not url.path.startswith(DESCRIPTION_PATH)):
        return None
    try:
        values = parse_qs(url.query, max_num_fields=64).get('productId', [])
    except ValueError:
        return None
    if len(values) == 1 and product_id(values[0]):
        return url.path, values[0]
    return None


def decode_product(body):
    try:
        text = body.decode('utf-8-sig')
        start = text.index('{')
        response, _ = json.JSONDecoder().raw_decode(text[start:])
    except (ValueError, RecursionError):
        return None
    if not isinstance(response, dict) or response.get('api') != 'mtop.aliexpress.pdp.pc.query':
        return None
    result = as_object(as_object(response.get('data')).get('result'))
    data = as_object(as_object(result.get('GLOBAL_DATA')).get('globalData'))
    price = as_object(result.get('PRICE'))
    key = product_id(data.get('productId'))
    title = public_text(as_object(result.get('PRODUCT_TITLE')).get('text'))
    if key is None or title is None or (price.get('productId') is not None and product_id(price['productId']) != key):
        return None
    return key, title, result


def cache_timestamp(value):
    try:
        return (WINDOWS_EPOCH + timedelta(microseconds=value)).isoformat() if value else None
    except OverflowError:
        return None


def variants(result):
    sku = as_object(result.get('SKU'))
    prices = as_object(result.get('PRICE'))
    offers = as_object(prices.get('skuIdStrPriceInfoMap')) or as_object(prices.get('skuPriceInfoMap'))
    options = {}
    for group in as_objects(sku.get('skuProperties')):
        for option in as_objects(group.get('skuPropertyValues')):
            key = f"{group.get('skuPropertyId')}:{option.get('propertyValueIdLong')}"
            options[key] = {
                'name': public_text(group.get('skuPropertyName')),
                'label': public_text(option.get('propertyValueDisplayName')) or public_text(option.get('propertyValueName')),
                'image_url': image_url(option.get('skuPropertyImagePath')),
            }
    rows = []
    seen = set()
    for choice in as_objects(sku.get('skuPaths')):
        key = product_id(choice.get('skuIdStr') or choice.get('skuId'))
        if key is None or key in seen:
            continue
        seen.add(key)
        path = public_text(choice.get('path')) or public_text(choice.get('skuAttr')) or ''
        option_keys = [value.partition('#')[0] for value in path.split(';')]
        offer = as_object(offers.get(key))
        original = as_object(offer.get('originalPrice'))
        stock = choice.get('skuStock')
        rows.append({
            'sku_id': key, 'options': [options[value] for value in option_keys if value in options],
            'stock_shown': stock if type(stock) is int and stock >= 0 else None,
            'offer': {
                'region': public_text(prices.get('region')),
                'currency': public_text(original.get('currency')),
                'displayed_price': public_text(offer.get('salePriceString')),
                'displayed_list_price': public_text(original.get('formatedAmount')),
            },
        })
    return rows


class DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = None
        self.parts = []
        self.length = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script', 'noscript') and self.hidden is None:
            self.hidden = tag

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data):
        if self.hidden is None and self.length < 8000:
            text = data.strip()[:8000 - self.length]
            if text:
                self.parts.append(text)
                self.length += len(text) + 1


def description(cache, entry):
    if entry is None:
        return None
    parser = DescriptionText()
    try:
        parser.feed(cache.body(entry).decode('utf-8', 'replace'))
        parser.close()
    except (AssertionError, ValueError):
        return None
    return '\n'.join(parser.parts) or None


def product_details(cache, entries, product, result):
    image_paths = as_object(result.get('HEADER_IMAGE_PC')).get('imagePathList')
    images = list(dict.fromkeys(
        url for value in image_paths if (url := image_url(value))
    )) if isinstance(image_paths, list) else []

    desc_url = as_object(result.get('DESC')).get('pcDescUrl')
    desc_key = description_key(cache_url(desc_url.encode('utf-8'))) if isinstance(desc_url, str) else None
    desc_entry = None
    if desc_key and desc_key[1] == product['source_product_id']:
        desc_entry = next((row for row in entries if description_key(row[0]) == desc_key), None)

    specifications = []
    for attribute in as_objects(as_object(result.get('PRODUCT_PROP_PC')).get('showedProps')):
        name, value = public_text(attribute.get('attrName')), public_text(attribute.get('attrValue'))
        if name and value:
            specifications.append({'name': name, 'value': value})
    return {
        **product, 'store': public_text(as_object(result.get('SHOP_CARD_PC')).get('storeName')),
        'main_image_urls': images, 'specifications': specifications, 'variants': variants(result),
        'description': description(cache, desc_entry),
    }


def cached_products(app, *, source_id=None, terms=(), limit=10):
    directory = app.parent / 'cache' / 'temp' / 'Cache'
    if source_id is not None and product_id(source_id) is None:
        raise ProductError('Use the numeric AliExpress item ID as --source-id.')
    terms = [term.strip().casefold() for term in terms if term.strip()]
    if not directory.is_dir():
        return {'ok': False, 'error': 'browser_cache_not_found', 'network_requests_sent': 0}

    with ExitStack() as stack:
        cache = BlockCache(directory, stack)
        # Newest indexed response wins when several responses describe the same product.
        entries = sorted(cache.entries(), key=lambda row: row[1], reverse=True)
        seen = set()
        records = []
        for entry in entries:
            if entry[0].hostname != 'acs.aliexpress.com':
                continue
            decoded = decode_product(cache.body(entry))
            if decoded is None:
                continue
            key, title, result = decoded
            if key in seen:
                continue
            seen.add(key)
            if ((source_id is not None and key != source_id) or
                    (terms and not any(term in title.casefold() for term in terms))):
                continue
            product = {'source_product_id': key, 'source_url': f'https://www.aliexpress.com/item/{key}.html',
                       'title': title, 'cached_at': cache_timestamp(entry[1])}
            if source_id is None:
                records.append(product)
                if len(records) == limit:
                    break
                continue

            return {'ok': True, 'source': 'aliexpress_browser_cache', 'network_requests_sent': 0,
                    'product': product_details(cache, entries, product, result)}
    if source_id is not None:
        return {'ok': False, 'error': 'source_product_not_cached', 'source_product_id': source_id,
                'network_requests_sent': 0}
    return {'ok': True, 'source': 'aliexpress_browser_cache', 'returned': len(records),
            'products': records, 'network_requests_sent': 0}
