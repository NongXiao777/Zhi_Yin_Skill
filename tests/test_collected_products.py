"""Exercise snapshot editing through the command line with synthetic data."""
import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CLI = Path(__file__).resolve().parents[1] / 'scripts' / 'zhiying.py'


class CollectedProductTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.source = self.root / 'product.json'
        self.output = self.root / 'edited.json'
        self.intro = self.root / 'intro.txt'
        self.intro.write_text('For indoor projects.\nChoose the required voltage.', encoding='utf-8')
        self.record = {
            'sale_id': 1001, 'sale_cur': 'USD', 'sale_cost': '8.2', 'sale_price': '11.00',
            'sale_weight': 240, 'sale_size': '13,10,9', 'unaffected': ['照片'],
            'sale_intro': json.dumps({'en': 'Old description', 'zh': '中文'}, ensure_ascii=False),
            'sale_stock': ('[{"key":"12V","money":0.3,"pic":"a","num":12},'
                           '{"key":"24V","money":0.2,"areas":{"rate":1.123456789123456789}}]'),
        }
        self.write_record()

    def write_record(self):
        self.source.write_text(json.dumps({'root': self.record, 'other': 1}), encoding='utf-8')

    def cli(self, command, *args, product_id='1001', expected=0, source=None):
        run = subprocess.run(
            [sys.executable, str(CLI), command, '--file', str(source or self.source),
             '--product-id', product_id, *map(str, args)],
            check=False, capture_output=True, encoding='utf-8',
        )
        self.assertEqual(run.returncode, expected, run.stderr + run.stdout)
        return json.loads(run.stdout)

    def test_edit_reloads_requested_changes_and_preserves_full_record(self):
        original = self.source.read_bytes()
        result = self.cli('collected-product-edit', '--adjust-surcharge', '12V', '0.10',
                          '--minimum-channel-price', '13.49', '--intro-file', self.intro,
                          '--limit', '1', '--output', self.output)
        self.assertEqual(result['business_requests_sent'], 0)
        self.assertTrue(result['local_read_back_verified'])
        self.assertEqual(result['variant_changes'], [{'key': '12V', 'old_money': '0.3', 'new_money': '0.40'}])
        self.assertEqual(result['channel_price_quote']['price'], '13.49')
        snapshot = json.loads(self.output.read_text(encoding='utf-8'))
        edited = snapshot['root']
        untouched = ('unaffected', 'sale_cost', 'sale_price', 'sale_weight', 'sale_size')
        self.assertEqual({key: edited[key] for key in untouched}, {key: self.record[key] for key in untouched})
        self.assertEqual(snapshot['other'], 1)
        stocks = json.loads(edited['sale_stock'], parse_float=Decimal)
        before = json.loads(self.record['sale_stock'], parse_float=Decimal)
        self.assertEqual(stocks, [{**before[0], 'money': Decimal('0.40')}, before[1]])
        self.assertEqual(json.loads(edited['sale_intro'])['zh'], '中文')
        loaded = self.cli('collected-product-get', '--include-intro', source=self.output)
        self.assertEqual(loaded['intro_en'], self.intro.read_text(encoding='utf-8'))
        self.assertEqual(loaded['total_variants'], 2)
        self.assertEqual(self.source.read_bytes(), original)

    def test_quote_rounds_up_independently_and_preview_skips_save(self):
        result = self.cli('collected-product-edit', '--set-surcharge', '12V', '0.5',
                          '--minimum-channel-price', '13.50')
        self.assertEqual(result['variant_changes'][0]['new_money'], '0.5')
        self.assertEqual(result['channel_price_quote']['price'], '13.89')
        self.assertNotIn('saved_to', result)
        loaded = self.cli('collected-product-get')
        self.assertEqual(loaded['variants'][0]['money'], '0.3')
        self.assertNotIn('intro_en', loaded)

    def test_zero_clears_legacy_surcharge_and_can_fill_missing_english(self):
        self.record['sale_stock'] = [{'key': 12, 'add': '0.3', 'num': 9}]
        self.record['sale_intro'] = {'zh': '中文'}
        self.write_record()
        self.cli('collected-product-edit', '--adjust-surcharge', '12', '-0.3',
                 '--intro-file', self.intro, '--output', self.output)
        edited = json.loads(self.output.read_text(encoding='utf-8'))['root']
        self.assertEqual(edited['sale_stock'], [{'key': 12, 'num': 9}])
        self.assertEqual(edited['sale_intro'], {'zh': '中文', 'en': self.intro.read_text(encoding='utf-8')})

    def test_mismatched_product_ambiguous_variant_and_existing_output_are_rejected(self):
        mismatch = self.cli('collected-product-get', product_id='1234', expected=1)
        self.assertIn('does not match', mismatch['error'])
        self.record['sale_stock'] = [{'key': '12V'}, {'key': '12V'}]
        self.write_record()
        ambiguous = self.cli('collected-product-edit', '--set-surcharge', '12V', '0.40',
                             '--output', self.output, expected=1)
        self.assertIn('exactly one', ambiguous['error'])
        self.assertFalse(self.output.exists())
        self.output.write_text('keep', encoding='utf-8')
        self.cli('collected-product-edit', '--intro-file', self.intro, '--output', self.output, expected=1)
        self.assertEqual(self.output.read_text(encoding='utf-8'), 'keep')

    def test_partial_copy_can_fill_local_title_and_preserves_other_fields(self):
        self.record['listing_copy'] = {'product_title': {'zh': '标题'}, 'bullet_points': {'en': 'Keep'}}
        self.write_record()
        self.intro.write_text(json.dumps({'product_title': 'Compact DC Motor'}), encoding='utf-8')
        result = self.cli('collected-product-edit', '--copy-file', self.intro, '--include-copy', '--output', self.output)
        self.assertEqual(result['copy_fields_changed'], ['product_title'])
        self.assertEqual(result['copy_en']['product_title'], 'Compact DC Motor')
        saved = json.loads(self.output.read_text(encoding='utf-8'))['root']
        self.assertEqual(saved['listing_copy']['product_title']['zh'], '标题')
        self.assertEqual(saved['listing_copy']['bullet_points']['en'], 'Keep')
        self.assertEqual(saved['sale_intro'], self.record['sale_intro'])

    def test_brand_and_affiliation_block_output(self):
        self.intro.write_text('Official Acme replacement.', encoding='utf-8')
        result = self.cli('collected-product-edit', '--intro-file', self.intro, '--blocked-brand', 'Acme',
                          '--output', self.output, expected=1)
        self.assertIn('blocked_brand', result['error'])
        self.assertIn('brand_affiliation_language', result['error'])
        self.assertFalse(self.output.exists())

    def test_append_and_two_surcharge_changes_preserve_exact_intro_and_other_data(self):
        before_text = '  Original <p>description</p>\r\n'
        self.record['sale_intro'] = json.dumps({'en': before_text, 'zh': '中文'}, ensure_ascii=False)
        self.write_record()
        original = self.source.read_bytes()
        result = self.cli('collected-product-edit', '--adjust-surcharge', '12V', '0.01',
                          '--adjust-surcharge', '24V', '0.01', '--append-intro', '*',
                          '--include-intro', '--output', self.output)
        self.assertTrue(result['local_read_back_verified'])
        self.assertEqual(result['intro_en'], before_text + '*')
        self.assertEqual(result['variant_changes'], [
            {'key': '12V', 'old_money': '0.3', 'new_money': '0.31'},
            {'key': '24V', 'old_money': '0.2', 'new_money': '0.21'}])
        saved = json.loads(self.output.read_text(encoding='utf-8'))['root']
        self.assertEqual(json.loads(saved['sale_intro']), {'en': before_text + '*', 'zh': '中文'})
        before = json.loads(self.record['sale_stock'], parse_float=Decimal)
        after = json.loads(saved['sale_stock'], parse_float=Decimal)
        self.assertEqual(after, [{**before[0], 'money': Decimal('0.31')},
                                 {**before[1], 'money': Decimal('0.21')}])
        self.assertEqual(saved['unaffected'], self.record['unaffected'])
        self.assertEqual(self.source.read_bytes(), original)

    def test_append_rejects_missing_english_instead_of_creating_a_marker_description(self):
        for existing in ({'zh': '中文'}, {'en': ''}, {'en': ' \n'}):
            with self.subTest(existing=existing):
                self.record['sale_intro'] = existing
                self.write_record()
                result = self.cli('collected-product-edit', '--append-intro', '*',
                                  '--output', self.output, expected=1)
                self.assertIn('existing nonempty English introduction', result['error'])
                self.assertFalse(self.output.exists())

    def test_append_conflicts_with_replacement_but_can_accompany_other_copy_fields(self):
        result = self.cli('collected-product-edit', '--append-intro', '*', '--intro-file', self.intro,
                          '--output', self.output, expected=1)
        self.assertIn('one option', result['error'])
        self.intro.write_text(json.dumps({'product_description': 'Replacement description'}), encoding='utf-8')
        result = self.cli('collected-product-edit', '--append-intro', '*', '--copy-file', self.intro,
                          '--output', self.output, expected=1)
        self.assertIn('one option', result['error'])
        self.assertFalse(self.output.exists())
        self.intro.write_text(json.dumps({'product_title': 'Compact DC Motor'}), encoding='utf-8')
        result = self.cli('collected-product-edit', '--append-intro', '*', '--copy-file', self.intro,
                          '--include-copy', '--output', self.output)
        self.assertEqual(result['copy_en']['product_description'], 'Old description*')
        self.assertEqual(result['copy_en']['product_title'], 'Compact DC Motor')

    def test_append_checks_combined_byte_limit_nonempty_suffix_and_brands(self):
        result = self.cli('collected-product-edit', '--append-intro', '', '--output', self.output, expected=1)
        self.assertIn('nonempty text', result['error'])
        result = self.cli('collected-product-edit', '--append-intro', ' Official Acme replacement.',
                          '--blocked-brand', 'Acme', '--output', self.output, expected=1)
        self.assertIn('blocked_brand', result['error'])
        self.assertFalse(self.output.exists())
        self.record['sale_intro'] = {'en': '字' * 83333}
        self.write_record()
        result = self.cli('collected-product-edit', '--append-intro', '字', '--output', self.output, expected=1)
        self.assertIn('exceeds 250 KB', result['error'])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
