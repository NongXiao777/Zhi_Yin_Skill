import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'zhiying.py'
SAMPLE = ROOT / 'examples' / 'erp-products.csv'


class ProductCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def run_cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True,
                                text=True, encoding='utf-8')
        self.assertEqual(result.returncode, code, msg=result.stderr + result.stdout)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_lookup_matches_exact_erp_id_before_limit(self):
        result = self.run_cli('erp-product-get', '--file', SAMPLE, '--product-id', 'DEMO-1001', '--limit', 1)
        self.assertEqual((result['total_variants'], result['returned']), (2, 1))
        self.assertEqual(result['variants'][0]['sku'], 'DEMO-BOX-W')
        self.assertEqual(result['variants'][0]['package_cm'], ['18', '12', '9'])
        self.assertEqual(result['business_requests_sent'], 0)
        missing = self.run_cli('erp-product-get', '--file', SAMPLE, '--product-id', 'DEMO-100', code=1)
        self.assertIn('No product rows matched', missing['error'])

    def test_preview_applies_rule_to_all_variants_and_saves_complete_draft(self):
        saved = self.folder / 'preview.json'
        args = ('erp-draft-preview', '--file', SAMPLE, '--product-id', 'DEMO-1001', '--add-amount', '3.25',
                '--currency', 'CNY', '--gross-weight-g', '370', '--package-cm', '19×13×10', '--limit', 1,
                '--output', saved)
        result = self.run_cli(*args)
        full = json.loads(saved.read_text(encoding='utf-8'))
        self.assertTrue(result['ready_for_review'])
        self.assertEqual(result['returned'], 1)
        self.assertEqual([row['proposed_price'] for row in full['variants']], ['23.25', '24.75'])
        self.assertEqual([row['gross_weight_g'] for row in full['variants']], ['370', '370'])
        self.assertEqual(full['variants'][1]['package_cm'], ['19', '13', '10'])
        self.assertEqual(full['business_requests_sent'], 0)
        self.assertIn('already exists', self.run_cli(*args, code=1)['error'])

    def test_missing_fields_duplicates_and_mixed_currency_are_visible(self):
        path = self.folder / 'ambiguous.json'
        path.write_text(json.dumps({'rows': [
            {'product_id': '001', 'sku': 'DUP', 'currency': 'USD', 'base_price': '10.125'},
            {'product_id': '001', 'sku': 'DUP', 'currency': 'CNY', 'base_price': '8.50'},
            {'product_id': '001', 'variant': 'gray', 'currency': 'USD', '成本价': '9'},
        ]}), encoding='utf-8')
        result = self.run_cli('erp-draft-preview', '--file', path, '--product-id', '001', '--markup-percent', '10',
                              '--currency', 'USD')
        self.assertFalse(result['ready_for_review'])
        self.assertEqual(result['issue_counts']['duplicate_sku'], 2)
        self.assertEqual(result['issue_counts']['missing_gross_weight_g'], 3)
        self.assertEqual(result['issue_counts']['missing_base_price'], 1)
        self.assertEqual(result['issue_counts']['currency_mismatch'], 1)
        self.assertEqual([row['proposed_price'] for row in result['variants']], ['11.14', None, None])

    def test_cost_column_requires_explicit_selection(self):
        path = self.folder / 'cost.tsv'
        path.write_text('父SKU\tSKU\t成本单价\t毛重(克)\t包装尺寸(厘米)\nBOX\tBLUE\t2.50\t20\t1*2*3\n',
                        encoding='gb18030')
        args = ('erp-draft-preview', '--file', path, '--parent-sku', 'BOX', '--add-amount', '2')
        error = self.run_cli(*args, code=1)
        self.assertIn('requires --currency', error['error'])
        result = self.run_cli(*args, '--currency', 'CNY', '--price-column', '成本单价')
        self.assertTrue(result['ready_for_review'])
        self.assertEqual(result['variants'][0]['proposed_price'], '4.50')

    def test_description_extracts_only_labeled_packaging_and_flags_conflicts(self):
        path = self.folder / 'descriptions.json'
        path.write_text(json.dumps([
            {'product_id': '001', 'sku': 'ONE', 'currency': 'USD', 'base_price': '5',
             'description': 'Net weight: 30 g\nGross weight: 0.125 kg\nPackage dimensions: 2 x 3 x 5 inches'},
            {'product_id': '001', 'sku': 'TWO', 'currency': 'USD', 'base_price': '6',
             'description': 'Gross weight: 50 g\nGross weight: 65 g\nItem size: 2 x 3 x 5 cm'},
        ]), encoding='utf-8')
        result = self.run_cli('erp-product-get', '--file', path, '--product-id', '001')
        precise, ambiguous = result['variants']
        self.assertEqual(precise['gross_weight_g'], '125.000')
        self.assertEqual(precise['package_cm'], ['5.08', '7.62', '12.70'])
        self.assertEqual(precise['gross_weight_source'], 'description')
        self.assertEqual(ambiguous['issues'], ['conflicting_gross_weight_g_in_description', 'missing_package_cm'])

    def test_packaging_estimate_fills_gaps_preserves_existing_values_and_needs_no_price(self):
        path = self.folder / 'packing.json'
        path.write_text(json.dumps([
            {'product_id': '001', 'sku': 'MEASURED', 'gross_weight_g': '195', 'package_cm': [12, 9, 6]},
            {'product_id': '001', 'sku': 'ESTIMATED'},
        ]), encoding='utf-8')
        args = ('erp-draft-preview', '--file', path, '--product-id', '001', '--estimated-gross-weight-g', '200',
                '--estimated-package-cm', '13x10x8')
        self.assertIn('--estimate-basis', self.run_cli(*args, code=1)['error'])
        result = self.run_cli(*args, '--estimate-basis', 'Single unit in a foam-lined carton')
        self.assertTrue(result['ready_for_review'])
        measured, estimated = result['variants']
        self.assertEqual((measured['gross_weight_g'], measured['gross_weight_source']), ('195', 'column'))
        self.assertEqual((measured['package_cm'], measured['package_size_source']), (['12', '9', '6'], 'column'))
        self.assertEqual((estimated['gross_weight_g'], estimated['gross_weight_source']), ('200', 'estimated'))
        self.assertEqual(estimated['package_estimate_basis'], 'Single unit in a foam-lined carton')
        self.assertNotIn('proposed_price', estimated)

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'XLSX support uses optional openpyxl')
    def test_xlsx_reads_named_sheet(self):
        from openpyxl import Workbook

        path = self.folder / 'products.xlsx'
        book = Workbook()
        book.active.title = '说明'
        sheet = book.create_sheet('产品')
        sheet.append(['产品编号', 'SKU', '售价', '货币', '包装毛重（克）', '包装尺寸（cm）'])
        sheet.append(['0001', 'BOX', 2.5, 'USD', 100, '3x2x1'])
        book.save(path)
        book.close()
        result = self.run_cli('erp-product-get', '--file', path, '--sheet', '产品', '--product-id', '0001')
        self.assertEqual(result['variants'][0]['base_price'], '2.5')
        self.assertEqual(result['variants'][0]['product_id'], '0001')
        self.assertEqual(result['variants'][0]['gross_weight_g'], '100')
