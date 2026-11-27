"""Plan recovery and selective restoration using synthetic products only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import product_plans as plans
from collected_products import collection, encode_json
from erp_products import ProductError
from collected_transport import ClientReloginRequired, TransportConflict


class ProductPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'plan.local.json'
        self.record = {'sale_id': 1001, 'sale_stat': 3117, 'sale_log': 'old',
                       'sale_intro': '{"en":"Original","zh":"Keep"}',
                       'sale_stock': '[{"key":"A","money":1.44,"num":5},{"key":"B","num":6},{"key":"C","money":7.0}]'}
        self.original = deepcopy(self.record)
        self.writes = []
        self.timeout_after = False
        self.timeout_before = False
        self.read_failure = False
        self.patchers = [patch.object(plans, 'detail', side_effect=self.read),
                         patch.object(plans, 'request', side_effect=self.write)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.instruction = {'adjust_surcharge': [['A', '0.01'], ['B', '0.01']], 'append_intro': '*'}

    def read(self, transport, product_id, command):
        if self.read_failure:
            raise ProductError('Synthetic read failed')
        self.assertEqual(product_id, 1001)
        self.assertEqual(command, 'sale.detail')
        return deepcopy(self.record)

    def write(self, transport, payload):
        self.assertEqual(payload['command'], 'sale.update')
        self.assertEqual(payload['id'], 1001)
        self.assertEqual(payload['expected'], {field: self.record[field] for field in payload['fields']})
        self.writes.append(deepcopy(payload))
        if self.timeout_before:
            raise ProductError('Synthetic timeout before save')
        self.record.update(deepcopy(payload['fields']))
        self.record['sale_log'] = 'operation ' + str(len(self.writes))
        if self.timeout_after:
            raise ProductError('Synthetic response lost')
        return {'ok': True}

    def make_plan(self):
        return plans.create_plan(['synthetic'], 1001, 'sale', self.instruction, self.path)

    def test_batch_plan_apply_restore_and_server_log(self):
        preview = self.make_plan()
        self.assertFalse(preview['update_sent'])
        self.assertEqual(len(preview['changes']), 3)
        result = plans.apply_plan(['synthetic'], self.path)
        self.assertTrue(result['remote_read_back_verified'])
        self.assertEqual(result['verification']['other_changed_fields'], ['sale_log'])
        self.assertEqual(collection(self.record, 'sale_intro', dict), {'en': 'Original*', 'zh': 'Keep'})
        restored = plans.restore_plan(['synthetic'], self.path)
        self.assertTrue(restored['remote_read_back_verified'])
        self.assertEqual(collection(self.record, 'sale_stock', list), collection(self.original, 'sale_stock', list))
        self.assertEqual(collection(self.record, 'sale_intro', dict), collection(self.original, 'sale_intro', dict))
        self.assertEqual(self.record['sale_stat'], self.original['sale_stat'])

    def test_same_plan_cannot_apply_twice(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.assertEqual(len(self.writes), 1)

    def test_lost_save_response_blocks_replay_and_can_restore(self):
        self.make_plan()
        self.timeout_after = True
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.assertEqual(plans.inspect_plan(self.path)['state'], 'write_attempted')
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.timeout_after = False
        self.assertTrue(plans.restore_plan(['synthetic'], self.path)['remote_read_back_verified'])
        self.assertEqual(len(self.writes), 2)

    def test_no_save_after_timeout_restores_without_writing(self):
        self.make_plan()
        self.timeout_before = True
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.timeout_before = False
        result = plans.restore_plan(['synthetic'], self.path)
        self.assertFalse(result['update_sent'])
        self.assertTrue(result['remote_read_back_verified'])
        self.assertEqual(len(self.writes), 1)

    def test_restore_preserves_other_variant_inventory_and_languages(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        stock = collection(self.record, 'sale_stock', list)
        stock[0]['num'] = 50
        stock[2]['money'] = 99
        self.record['sale_stock'] = encode_json(stock)
        self.record['sale_intro'] = '{"en":"Original*","zh":"New unrelated text","fr":"Bonjour"}'
        result = plans.restore_plan(['synthetic'], self.path)
        self.assertTrue(result['remote_read_back_verified'])
        stock = collection(self.record, 'sale_stock', list)
        self.assertEqual(stock[0]['num'], 50)
        self.assertEqual(stock[0]['money'], Decimal('1.44'))
        self.assertNotIn('money', stock[1])
        self.assertEqual(stock[2]['money'], 99)
        self.assertEqual(collection(self.record, 'sale_intro', dict), {'en': 'Original', 'zh': 'New unrelated text', 'fr': 'Bonjour'})

    def test_restore_conflicting_target_stops_before_write(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        self.record['sale_intro'] = '{"en":"Independent edit","zh":"Keep"}'
        with self.assertRaises(ProductError):
            plans.restore_plan(['synthetic'], self.path)
        self.assertEqual(len(self.writes), 1)

    def test_changed_edited_column_stops_apply(self):
        self.make_plan()
        stock = collection(self.record, 'sale_stock', list)
        stock[2]['num'] = 20
        self.record['sale_stock'] = encode_json(stock)
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.assertFalse(self.writes)

    def test_log_change_since_preview_does_not_block_apply(self):
        self.make_plan()
        self.record['sale_log'] = 'unrelated operation'
        self.assertTrue(plans.apply_plan(['synthetic'], self.path)['remote_read_back_verified'])

    def test_tampered_expected_content_cannot_hide_second_variant_change(self):
        self.make_plan()
        document = plans._read_document(self.path)
        stock = collection(document['expected_record'], 'sale_stock', list)
        stock[2]['money'] = 99
        document['expected_record']['sale_stock'] = encode_json(stock)
        plans._write_document(self.path, document)
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.assertFalse(self.writes)

    def test_unsupported_field_cannot_be_added_to_expected_record(self):
        self.make_plan()
        document = plans._read_document(self.path)
        document['expected_record']['sale_stat'] = 999
        plans._write_document(self.path, document)
        with self.assertRaises(ProductError):
            plans.inspect_plan(self.path)

    def test_duplicate_variant_keys_rejected(self):
        self.record['sale_stock'] = '[{"key":"A"},{"key":"A"}]'
        with self.assertRaises(ProductError):
            self.make_plan()
        self.assertFalse(self.path.exists())

    def test_same_plan_concurrent_apply_is_locked(self):
        self.make_plan()
        entered, release = threading.Event(), threading.Event()
        original_read = self.read
        def delayed(*args):
            entered.set()
            if not release.wait(5):
                raise ProductError('Test failed to release')
            return original_read(*args)
        with patch.object(plans, 'detail', side_effect=delayed), ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(plans.apply_plan, ['synthetic'], self.path)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(ProductError):
                    plans.apply_plan(['synthetic'], self.path)
            finally:
                release.set()
            self.assertTrue(first.result()['remote_read_back_verified'])
        self.assertEqual(len(self.writes), 1)

    def test_unknown_restore_result_can_be_reconciled_without_duplicate_write(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        self.timeout_after = True
        with self.assertRaises(ProductError):
            plans.restore_plan(['synthetic'], self.path)
        self.timeout_after = False
        result = plans.restore_plan(['synthetic'], self.path)
        self.assertFalse(result['update_sent'])
        self.assertEqual(result['state'], 'restored')
        self.assertEqual(len(self.writes), 2)

    def test_completed_restore_reports_history_without_overwriting_later_edits(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        plans.restore_plan(['synthetic'], self.path)
        self.record['sale_intro'] = '{"en":"Later independent edit","zh":"Keep"}'
        with patch.object(plans, 'detail', side_effect=AssertionError('Historical no-op must not read')):
            result = plans.restore_plan(['synthetic'], self.path)
        self.assertTrue(result['previous_read_back_verified'])
        self.assertNotIn('remote_read_back_verified', result)
        self.assertEqual(len(self.writes), 2)

    def test_partial_restoration_preserves_unchanged_target_and_other_variant(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        stock = collection(self.record, 'sale_stock', list)
        stock[0]['money'] = Decimal('1.44')
        stock[2]['money'] = 99
        self.record['sale_stock'] = encode_json(stock)
        result = plans.restore_plan(['synthetic'], self.path)
        self.assertTrue(result['remote_read_back_verified'])
        stock = collection(self.record, 'sale_stock', list)
        self.assertEqual(stock[0]['money'], Decimal('1.44'))
        self.assertNotIn('money', stock[1])
        self.assertEqual(stock[2]['money'], 99)

    def test_target_price_independently_changed_stops_before_restore(self):
        self.make_plan()
        plans.apply_plan(['synthetic'], self.path)
        stock = collection(self.record, 'sale_stock', list)
        stock[0]['money'] = 9
        self.record['sale_stock'] = encode_json(stock)
        with self.assertRaises(ProductError):
            plans.restore_plan(['synthetic'], self.path)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(collection(self.record, 'sale_stock', list)[0]['money'], 9)

    def test_acknowledged_write_with_failed_readback_stays_recoverable(self):
        self.make_plan()
        original_read = self.read
        def failing_readback(*args):
            if self.writes:
                raise ProductError('Synthetic read-back failure')
            return original_read(*args)
        with patch.object(plans, 'detail', side_effect=failing_readback):
            with self.assertRaises(ProductError):
                plans.apply_plan(['synthetic'], self.path)
        self.assertEqual(plans.inspect_plan(self.path)['state'], 'write_attempted')
        with self.assertRaises(ProductError):
            plans.apply_plan(['synthetic'], self.path)
        self.assertTrue(plans.restore_plan(['synthetic'], self.path)['remote_read_back_verified'])
        self.assertEqual(len(self.writes), 2)

    def test_transport_rejection_before_a_write_keeps_plan_prepared(self):
        self.make_plan()
        for error in (TransportConflict, ClientReloginRequired):
            with self.subTest(error=error):
                with patch.object(plans, 'request', side_effect=error('Rejected before remote write')):
                    with self.assertRaises(error):
                        plans.apply_plan(['synthetic'], self.path)
                self.assertEqual(plans.inspect_plan(self.path)['state'], 'prepared')
                self.assertFalse(self.writes)

    def test_semantically_equivalent_json_does_not_fail_baseline_check(self):
        self.make_plan()
        stock = collection(self.record, 'sale_stock', list)
        stock[1]['money'] = 0
        self.record['sale_stock'] = encode_json(stock)
        self.record['sale_intro'] = '{ "zh" : "Keep", "en" : "Original" }'
        self.assertTrue(plans.apply_plan(['synthetic'], self.path)['remote_read_back_verified'])

    def test_collection_route_stays_on_spider_for_read_write_and_verify(self):
        self.make_plan()
        document = plans._read_document(self.path)
        document['namespace'] = 'spider'
        plans._write_document(self.path, document)
        read_commands, writes = [], []
        def read(transport, number, command):
            self.assertEqual(number, 1001)
            read_commands.append(command)
            return deepcopy(self.record)
        def write(transport, payload):
            writes.append(payload['command'])
            self.record.update(payload['fields'])
            return {'ok': True}
        with patch.object(plans, 'detail', side_effect=read), patch.object(plans, 'request', side_effect=write):
            self.assertTrue(plans.apply_plan(['synthetic'], self.path)['remote_read_back_verified'])
            self.assertTrue(plans.restore_plan(['synthetic'], self.path)['remote_read_back_verified'])
        self.assertEqual(read_commands, ['spider.detail'] * 4)
        self.assertEqual(writes, ['spider.update'] * 2)

    def test_variant_metadata_cannot_be_added_to_a_plan(self):
        self.make_plan()
        document = plans._read_document(self.path)
        stock = collection(document['expected_record'], 'sale_stock', list)
        stock[0]['pic'] = 'independent.jpg'
        document['expected_record']['sale_stock'] = encode_json(stock)
        plans._write_document(self.path, document)
        with self.assertRaises(ProductError):
            plans.inspect_plan(self.path)

    def test_plan_creation_never_overwrites_an_existing_file(self):
        self.make_plan()
        saved = self.path.read_bytes()
        with self.assertRaises(ProductError):
            self.make_plan()
        self.assertEqual(self.path.read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
