import gzip
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collected_cache import cached_products


PDP = 'https://acs.aliexpress.com/h5/mtop.aliexpress.pdp.pc.query/1.0/'
DESCRIPTION = 'https://pdp.aliexpress-media.com/product/description/pc/v2/en_US/desc.htm'


def product_response(product_id, title, **fields):
    result = {
        'GLOBAL_DATA': {'globalData': {'productId': product_id, 'securityToken': 'sensitive-fixture-token'}},
        'PRODUCT_TITLE': {'text': title},
        'PRICE': {'productId': product_id},
        **fields,
    }
    response = {'api': 'mtop.aliexpress.pdp.pc.query', 'data': {'result': result}}
    return ('fixture_callback(' + json.dumps(response) + ')').encode()


class CacheFixture:
    def __init__(self, app):
        self.root = app.parent / 'cache' / 'temp' / 'Cache'
        self.root.mkdir(parents=True)
        self.blocks = bytearray(8192)
        self.indexed = []
        self.next_file = 1
        struct.pack_into('<IIhhi', self.blocks, 0, 0xC104CAC3, 0x20000, 1, 0, 256)

    def external(self, content):
        number = self.next_file
        self.next_file += 1
        (self.root / f'f_{number:06x}').write_bytes(content)
        return 0x80000000 | number

    def add(self, url, body, created, *, indexed=True, state=0, next_address=0):
        key = ('1/0/' + url).encode()
        header = b'HTTP/1.1 200 OK\0Content-Encoding: gzip\0'
        compressed = gzip.compress(body)
        block = bytearray(256)
        struct.pack_into('<II', block, 0, 1, next_address)
        struct.pack_into('<iQiI', block, 20, state, created, len(key), self.external(key))
        struct.pack_into('<4i', block, 40, len(header), len(compressed), 0, 0)
        struct.pack_into('<4I', block, 56, self.external(header), self.external(compressed), 0, 0)
        address = 0xA0010000 | ((len(self.blocks) - 8192) // 256)
        self.blocks.extend(block)
        if indexed:
            self.indexed.append(address)
        return address

    def commit(self):
        table = self.indexed + [0]
        index = bytearray(368 + 4 * len(table))
        struct.pack_into('<II', index, 0, 0xC103CAC3, 0x20001)
        struct.pack_into('<i', index, 28, len(table))
        struct.pack_into(f'<{len(table)}I', index, 368, *table)
        (self.root / 'index').write_bytes(index)
        (self.root / 'data_1').write_bytes(self.blocks)


class CollectedCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = Path(directory.name) / 'ZYing.exe'
        self.cache = CacheFixture(self.app)

    def test_list_follows_index_chains_and_ignores_stale_or_malformed_rows(self):
        old = self.cache.add(PDP, product_response('101', 'Old clay'), 1, indexed=False)
        self.cache.add(PDP, product_response('101', 'Polymer Clay'), 4, next_address=old)
        self.cache.add(PDP, product_response('102', 'Crayons'), 2, indexed=False)
        self.cache.add(PDP, product_response('103', 'Canvas'), 8, state=2)
        self.cache.add(PDP, b'not a product', 9)
        self.cache.add(PDP, product_response('104', 'Paint Brushes'), 3)
        self.cache.commit()

        result = cached_products(self.app, terms=['CLAY', 'Paint'])
        self.assertEqual([(p['source_product_id'], p['title']) for p in result['products']],
                         [('101', 'Polymer Clay'), ('104', 'Paint Brushes')])
        self.assertEqual(cached_products(self.app, terms=['crayon'])['returned'], 0)
        self.assertEqual(cached_products(self.app, source_id='102')['error'], 'source_product_not_cached')

    def test_get_uses_exact_source_id_and_returns_public_fields_for_each_sku(self):
        desc = DESCRIPTION + '?productId=101&token=sensitive-fixture-token'
        result = product_response('101', 'Clay', **{
            'DESC': {'pcDescUrl': desc},
            'HEADER_IMAGE_PC': {'imagePathList': [
                '//ae-pic-a1.aliexpress-media.com/kf/one.jpg?token=sensitive-fixture-token',
                'https://example.com/image.jpg',
            ]},
            'SKU': {
                'skuPaths': [
                    {'skuIdStr': '120000000000000001', 'path': '14:193', 'skuStock': 4},
                    {'skuIdStr': '120000000000000002', 'skuAttr': '14:194#Red', 'skuStock': 0},
                ],
                'skuProperties': [{'skuPropertyId': 14, 'skuPropertyName': 'Color', 'skuPropertyValues': [
                    {'propertyValueIdLong': 193, 'propertyValueDisplayName': 'Black'},
                    {'propertyValueIdLong': 194, 'propertyValueDisplayName': 'Red'},
                ]}],
            },
        })
        self.cache.add(PDP + '?q=101', result, 5)
        self.cache.add(DESCRIPTION + '?productId=102', b'<p>Wrong product</p>', 6)
        self.cache.add(desc, b'<p>Oven bake clay</p><script>sensitive-fixture-token</script>', 3)
        self.cache.commit()

        report = cached_products(self.app, source_id='101')
        product = report['product']
        self.assertEqual(report['network_requests_sent'], 0)
        self.assertEqual(product['description'], 'Oven bake clay')
        self.assertEqual(product['main_image_urls'], ['https://ae-pic-a1.aliexpress-media.com/kf/one.jpg'])
        self.assertEqual([row['options'][0]['label'] for row in product['variants']], ['Black', 'Red'])
        self.assertEqual([row['stock_shown'] for row in product['variants']], [4, 0])
        self.assertNotIn('sensitive-fixture-token', json.dumps(report))
