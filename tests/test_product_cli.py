from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import product_cli
from product_model import ProductDataError, decode_json


class FakeClient:
    def __init__(self):
        self.record = {'sale_id': 951393413, 'sale_title': '{"en":"Motor"}',
                       'sale_intro': '{"en":"Description","zh":"原文"}',
                       'sale_stock': '[{"key":"A","money":7.0},{"key":"B","money":5.0}]',
                       'sale_stat': 100}
        self.writes = []
        self.timeout_after_write = False

    def read_detail(self, namespace, product_id):
        return {'root': [deepcopy(self.record)]}

    def update_fields(self, namespace, product_id, fields):
        self.writes.append(deepcopy(fields))
        self.record.update(fields)
        if self.timeout_after_write:
            raise TimeoutError('The response was lost')


class ProductCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'plan.json'
        self.client = FakeClient()
        self.original = deepcopy(self.client.record)
        self.instruction = {'operation': 'update_product', 'product_id': 951393413,
                            'namespace': 'sale', 'variant_key': 'A', 'new_money': '7.01',
                            'description_language': 'en', 'append_character': '＊'}
        product_cli.create_plan(self.client, self.instruction, self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_apply_and_restore_preserve_other_fields(self):
        result = product_cli.apply_plan(self.client, self.path)
        self.assertTrue(result['ok'])
        self.assertEqual(set(self.client.writes[0]), {'sale_stock', 'sale_intro'})
        self.assertEqual(decode_json(self.client.record['sale_stock'])[1], {'key': 'B', 'money': 5})
        restored = product_cli.restore_plan(self.client, self.path)
        self.assertTrue(restored['ok'])
        self.assertEqual(self.client.record, self.original)

    def test_lost_response_persists_write_intent_and_blocks_replay(self):
        self.client.timeout_after_write = True
        with self.assertRaises(TimeoutError):
            product_cli.apply_plan(self.client, self.path)
        self.assertEqual(product_cli._read_document(self.path)['state'], 'write_attempted')
        with self.assertRaises(ProductDataError):
            product_cli.apply_plan(self.client, self.path)
        self.assertEqual(len(self.client.writes), 1)
        self.client.timeout_after_write = False
        self.assertTrue(product_cli.restore_plan(self.client, self.path)['ok'])

    def test_stale_read_cannot_overwrite_intervening_changes(self):
        self.client.record['sale_stat'] = 200
        with self.assertRaises(ProductDataError):
            product_cli.apply_plan(self.client, self.path)
        self.assertFalse(self.client.writes)
        self.assertEqual(product_cli._read_document(self.path)['state'], 'prepared')

    def test_restore_refuses_competing_changes_to_target(self):
        product_cli.apply_plan(self.client, self.path)
        self.client.record['sale_intro'] = '{"en":"Someone else changed it"}'
        with self.assertRaises(ProductDataError):
            product_cli.restore_plan(self.client, self.path)
        self.assertEqual(len(self.client.writes), 1)

    def test_plan_with_extra_update_field_is_rejected(self):
        document = product_cli._read_document(self.path)
        document['updates']['sale_stat'] = 200
        product_cli._write_document(self.path, document)
        with self.assertRaises(ProductDataError):
            product_cli.apply_plan(self.client, self.path)
        self.assertFalse(self.client.writes)

    def test_concurrent_apply_cannot_submit_the_same_plan_twice(self):
        entered = threading.Event()
        release = threading.Event()
        original_read = self.client.read_detail

        def delayed_read(namespace, product_id):
            result = original_read(namespace, product_id)
            if not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('The test did not release the read')
            return result

        self.client.read_detail = delayed_read
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(product_cli.apply_plan, self.client, self.path)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(ProductDataError):
                    product_cli.apply_plan(self.client, self.path)
            finally:
                release.set()
            self.assertTrue(first.result()['ok'])
        self.assertEqual(len(self.client.writes), 1)


if __name__ == '__main__':
    unittest.main()
