"""Check offline selling-price quotes against explicitly supplied costs and targets."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from erp_products import ProductError
from pricing import pricing_quote, quote_spec


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'currency': 'USD', 'unit_cost': '10', 'shipping_cost': '2',
                     'packaging_cost': '0.50', 'other_cost': '0.50',
                     'platform_fee_rate': '0.15', 'target_profit': '4'}

    def test_profit_target_includes_every_supplied_cost_and_price_based_fee(self):
        before = deepcopy(self.spec)
        result = quote_spec(self.spec)
        self.assertEqual(result['total_cost'], '13.00')
        self.assertEqual(Decimal(result['required_price']), Decimal('20'))
        self.assertEqual(result['quoted_price'], '20.49')
        self.assertEqual(Decimal(result['projected_platform_fee']), Decimal('3.0735'))
        self.assertEqual(Decimal(result['projected_net_profit']), Decimal('4.4165'))
        self.assertTrue(result['target_met'])
        self.assertEqual(result['business_requests_sent'], 0)
        self.assertFalse(result['erp_surcharge_inferred'])
        self.assertEqual(self.spec, before)

    def test_margin_target_is_net_profit_divided_by_selling_price(self):
        self.spec.pop('target_profit')
        self.spec.update(target_margin='0.20', unit_cost='12', shipping_cost='0',
                         packaging_cost='0', other_cost='0', platform_fee_rate='0.10')
        result = quote_spec(self.spec)
        self.assertEqual(result['quoted_price'], '17.49')
        self.assertGreaterEqual(Decimal(result['projected_net_margin']), Decimal('0.20'))
        self.assertTrue(result['target_met'])
        self.assertNotIn('target_profit', result)

    def test_rounding_chooses_the_lowest_permitted_ending_at_or_above_minimum(self):
        cases = [('13.30', '13.49'), ('13.49', '13.49'), ('13.490000000000000001', '13.89'),
                 ('13.50', '13.89'), ('13.89', '13.89'), ('13.890000000000000001', '13.99'),
                 ('13.99', '13.99'), ('13.990000000000000001', '14.49')]
        for minimum, expected in cases:
            with self.subTest(minimum=minimum):
                self.spec.update(unit_cost=minimum, shipping_cost='0', packaging_cost='0',
                                 other_cost='0', platform_fee_rate='0', target_profit='0')
                result = quote_spec(self.spec)
                self.assertEqual(result['quoted_price'], expected)
                self.assertGreaterEqual(Decimal(result['quoted_price']), Decimal(minimum))

    def test_zero_cost_and_zero_target_still_use_an_allowed_price(self):
        self.spec.update(unit_cost='0', shipping_cost='0', packaging_cost='0',
                         other_cost='0', platform_fee_rate='0', target_profit='0')
        result = quote_spec(self.spec)
        self.assertEqual(result['quoted_price'], '0.49')
        self.assertTrue(result['target_met'])

    def test_fee_and_margin_boundary_values_are_rejected(self):
        for fee in ('1', '1.01', '-0.01'):
            with self.subTest(fee=fee):
                self.spec['platform_fee_rate'] = fee
                with self.assertRaises(ProductError):
                    quote_spec(self.spec)
        self.spec.pop('target_profit')
        for fee, margin in (('0.15', '0.85'), ('0.20', '0.90'), ('0', '1'), ('0', '-0.01')):
            with self.subTest(fee=fee, margin=margin):
                self.spec.update(platform_fee_rate=fee, target_margin=margin)
                with self.assertRaises(ProductError):
                    quote_spec(self.spec)

    def test_small_positive_denominator_produces_a_quote_meeting_target(self):
        self.spec.update(unit_cost='1', shipping_cost='0', packaging_cost='0', other_cost='0',
                         platform_fee_rate='0.999999999999999999', target_profit='0')
        result = quote_spec(self.spec)
        self.assertTrue(result['target_met'])
        self.assertEqual(result['quoted_price'], '1000000000000000000.49')

    def test_missing_conflicting_and_nonfinite_inputs_fail(self):
        for field in ('unit_cost', 'shipping_cost', 'packaging_cost', 'other_cost',
                      'platform_fee_rate', 'currency'):
            with self.subTest(missing=field):
                spec = {key: value for key, value in self.spec.items() if key != field}
                with self.assertRaises(ProductError):
                    quote_spec(spec)
        for value in ('NaN', 'Infinity', '-Infinity', '-1', True, None, {}, '1e9999', '0e99999999'):
            with self.subTest(value=value):
                with self.assertRaises(ProductError):
                    quote_spec({**self.spec, 'unit_cost': value})
        with self.assertRaises(ProductError):
            quote_spec({**self.spec, 'target_margin': '0.2'})
        with self.assertRaises(ProductError):
            quote_spec({key: value for key, value in self.spec.items() if key != 'target_profit'})
        for currency in ('US', 'USDX', 'U$D', 123):
            with self.subTest(currency=currency):
                with self.assertRaises(ProductError):
                    quote_spec({**self.spec, 'currency': currency})

    def test_optional_comparison_does_not_infer_new_erp_surcharge(self):
        result = quote_spec({**self.spec, 'channel_base_price': '25', 'current_surcharge': '0.30'})
        self.assertEqual(result['comparison'], {'channel_base_price': '25',
                                               'quoted_price_delta': '-4.51',
                                               'reported_current_surcharge': '0.30', 'comparison_only': True})
        self.assertFalse(result['erp_surcharge_inferred'])
        self.assertNotIn('money', result)
        self.assertNotIn('proposed_surcharge', result)

    def test_file_quote_accepts_exact_json_decimals_and_preserves_source(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'pricing.json'
            text = ('{"currency":"usd","unit_cost":10,"shipping_cost":2,"packaging_cost":0.50,'
                    '"other_cost":0.50,"platform_fee_rate":0.15,"target_profit":4}')
            path.write_text(text, encoding='utf-8')
            result = pricing_quote(path)
            self.assertEqual(result['currency'], 'USD')
            self.assertEqual(result['quoted_price'], '20.49')
            self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_duplicate_fields_or_invalid_json_are_rejected(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'pricing.json'
            for text in ('{"unit_cost":1,"unit_cost":2}', '{bad', '[]'):
                with self.subTest(text=text):
                    path.write_text(text, encoding='utf-8')
                    with self.assertRaises(ProductError):
                        pricing_quote(path)


if __name__ == '__main__':
    unittest.main()
