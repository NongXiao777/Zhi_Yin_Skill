import importlib.util
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('product_model', ROOT / 'scripts' / 'product_model.py')
model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)


class ProductModelTests(unittest.TestCase):
    def response(self):
        return {'root': [{'sale_id': 951393413,
                          'sale_title': '{"en":"Motor","zh":"电机"}',
                          'sale_intro': '{"en":"Description","zh":"原中文"}',
                          'sale_stock': '[{"key":"A","money":7.00,"no":"SKU-A","custom":{"v":1}},'
                                        '{"key":"B","money":5.00,"areas":["US"]}]',
                          'sale_cur': 'CNY', 'sale_weight': 200, 'sale_size': '20,15,10',
                          'sale_stat': 100, 'unknown_column': 'preserve'}],
                'stock': [{'key': 'A', 'num': 3998}]}

    def snapshot(self, response=None):
        return model.parse_snapshot(response or self.response(), 951393413)

    def test_surcharge_preserves_complete_collection_and_unknown_fields(self):
        before = self.snapshot()
        plan = model.plan_changes(before, variant_key='A', new_money=Decimal('7.01'))
        variants = model.decode_json(plan.updates['sale_stock'])
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[1], before.variants[1])
        self.assertEqual(variants[0]['custom'], {'v': 1})
        self.assertEqual(variants[0]['money'], Decimal('7.01'))
        self.assertEqual(before.variants[0]['money'], Decimal('7'))
        self.assertEqual(set(plan.updates), {'id', 'sale_stock'})

    def test_money_does_not_round_through_binary_float(self):
        plan = model.plan_changes(self.snapshot(), variant_key='A', new_money='7.01')
        self.assertIn('"money":7.01', plan.updates['sale_stock'])
        self.assertNotIn('7.00999', plan.updates['sale_stock'])
        with self.assertRaises(model.ProductDataError):
            model.plan_changes(self.snapshot(), variant_key='A', new_money=7.01)

    def test_overprecision_and_decimal_range_are_rejected(self):
        for value in ('7.00001', Decimal('NaN'), '79228162514264337593543950336'):
            with self.subTest(value=value), self.assertRaises(model.ProductDataError):
                model.decimal_amount(value)
        self.assertEqual(model.decimal_amount('7.01000'), Decimal('7.01'))
        self.assertEqual(model.decimal_amount('0.000000'), Decimal(0))
        with self.assertRaises(model.ProductDataError):
            model.decimal_amount(Decimal('1e100000'))

    def test_description_preserves_all_other_languages(self):
        plan = model.plan_changes(self.snapshot(), description_language='en', append_character='＊')
        descriptions = model.decode_json(plan.updates['sale_intro'])
        self.assertEqual(descriptions, {'en': 'Description＊', 'zh': '原中文'})
        self.assertEqual(plan.restore_updates['sale_intro'], self.response()['root'][0]['sale_intro'])
        self.assertNotIn('sale_title', plan.updates)

    def test_combined_plan_can_be_read_back_and_restored(self):
        before = self.snapshot()
        plan = model.plan_changes(before, 'A', '7.01', 'en', '＊')
        response = self.response()
        response['root'][0].update({name: value for name, value in plan.updates.items() if name != 'id'})
        after = self.snapshot(response)
        self.assertTrue(model.verify_readback(before, after, plan)['verified'])
        response['root'][0].update({name: value for name, value in plan.restore_updates.items() if name != 'id'})
        self.assertTrue(model.verify_restore(before, self.snapshot(response))['restored'])

    def test_unrelated_changes_fail_readback(self):
        before = self.snapshot()
        plan = model.plan_changes(before, 'A', '7.01')
        response = self.response()
        response['root'][0]['sale_stock'] = plan.updates['sale_stock']
        response['root'][0]['sale_stat'] = 200
        result = model.verify_readback(before, self.snapshot(response), plan)
        self.assertFalse(result['verified'])
        self.assertEqual(result['unexpected_fields'], ['sale_stat'])

    def test_stale_snapshot_rejected_before_save(self):
        original = self.snapshot()
        plan = model.plan_changes(original, 'A', '7.01')
        changed = self.response()
        changed['root'][0]['unknown_column'] = 'concurrent change'
        with self.assertRaises(model.ProductDataError):
            model.assert_base_unchanged(self.snapshot(changed), plan)

    def test_duplicate_variant_keys_rejected(self):
        response = self.response()
        response['root'][0]['sale_stock'] = '[{"key":"A"},{"key":"A","money":2}]'
        with self.assertRaises(model.ProductDataError):
            self.snapshot(response)

    def test_missing_or_wrong_variant_key_rejected(self):
        response = self.response()
        response['root'][0]['sale_stock'] = '[{"no":"SKU-A"}]'
        with self.assertRaises(model.ProductDataError):
            self.snapshot(response)
        with self.assertRaises(model.ProductDataError):
            model.plan_changes(self.snapshot(), 'SKU-A', '7.01')

    def test_wrong_product_id_and_multiple_root_rows_rejected(self):
        response = self.response()
        response['root'][0]['sale_id'] = 42
        with self.assertRaises(model.ProductDataError):
            self.snapshot(response)
        response = self.response()
        response['root'].append(deepcopy(response['root'][0]))
        with self.assertRaises(model.ProductDataError):
            self.snapshot(response)

    def test_zero_surcharge_and_legacy_alias(self):
        response = self.response()
        response['root'][0]['sale_stock'] = '[{"key":"A","add":1.0},{"key":"B"}]'
        snapshot = self.snapshot(response)
        self.assertEqual(model.compact_summary(snapshot)['variants'][1]['surcharge'], '0.0')
        plan = model.plan_changes(snapshot, 'A', '0')
        variants = model.decode_json(plan.updates['sale_stock'])
        self.assertNotIn('money', variants[0])
        self.assertNotIn('add', variants[0])
        self.assertEqual(variants[1], {'key': 'B'})

    def test_duplicate_json_and_conflicting_alias_rejected(self):
        with self.assertRaises(model.ProductDataError):
            model.decode_json('{"key":"A","key":"B"}')
        response = self.response()
        response['root'][0]['sale_stock'] = '[{"key":"A","money":1,"add":2}]'
        with self.assertRaises(model.ProductDataError):
            self.snapshot(response)

    def test_legacy_description_and_paged_root(self):
        response = self.response()
        response['root'][0]['sale_intro'] = '旧介绍'
        response['root'] = {'page': 1, 'data': response['root']}
        snapshot = self.snapshot(response)
        self.assertEqual(snapshot.descriptions, {'zh': '旧介绍'})
        plan = model.plan_changes(snapshot, description_language='zh', append_character='+')
        self.assertEqual(model.decode_json(plan.updates['sale_intro']), {'zh': '旧介绍+'})

    def test_visibility_and_no_op_requirements(self):
        for character in (' ', '\n', '\u200b', '\u0301', 'ab'):
            with self.subTest(character=character), self.assertRaises(model.ProductDataError):
                model.plan_changes(self.snapshot(), description_language='en', append_character=character)
        with self.assertRaises(model.ProductDataError):
            model.plan_changes(self.snapshot(), 'A', '7.00')

    def test_fingerprint_ignores_json_formatting_but_not_content(self):
        before = self.snapshot()
        response = self.response()
        response['root'][0]['sale_intro'] = '{ "zh" : "原中文", "en" : "Description" }'
        response['root'][0]['sale_stock'] = model.encode_json(before.variants)
        self.assertEqual(model.fingerprint(before), model.fingerprint(self.snapshot(response)))

    def test_native_double_column_is_preserved_without_float_surcharge(self):
        response = self.response()
        response['root'][0]['native_double'] = 3.25
        before = self.snapshot(response)
        plan = model.plan_changes(before, 'A', '7.01')
        self.assertEqual(plan.expected_record['native_double'], 3.25)
        self.assertEqual(model.decode_json(model.encode_json(plan.expected_record))['native_double'], Decimal('3.25'))
        self.assertEqual(len(model.fingerprint(before)), 64)


if __name__ == '__main__':
    unittest.main()
