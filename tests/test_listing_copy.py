import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'zhiying.py'
COPY = {
    'product_title': 'Panel Mount Cable Gland for 4 to 8 mm Cable, 1 Piece',
    'product_highlight': 'Threaded body and locknut mount through a matching panel opening.',
    'bullet_points': ['Threaded mount', 'Cable diameter range', 'Locknut included', 'Single fitting', 'Panel use'],
    'product_description': 'Overview\nThis cable gland provides a mounting point for a cable through a panel.',
    'backend_search_terms': 'cord entry fitting',
}


class ListingCopyCLITests(unittest.TestCase):
    def run_cli(self, draft, *args, exit_code=0):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'draft.json'
            path.write_text(json.dumps(draft), encoding='utf-8')
            response = subprocess.run([sys.executable, str(SCRIPT), 'listing-copy-check', '--file', str(path), *args],
                                      capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(response.returncode, exit_code, msg=response.stderr + response.stdout)
        return json.loads(response.stdout)

    def test_maps_five_erp_fields_and_accepts_empty_search_terms(self):
        result = self.run_cli({**COPY, 'backend_search_terms': ''}, '--erp-fields')
        self.assertTrue(result['copy_checks_pass'])
        self.assertEqual(result['backend_utf8_bytes'], 0)
        self.assertEqual(result['erp_fields']['要点说明'].splitlines(), COPY['bullet_points'])
        self.assertEqual(result['erp_fields']['产品描述'], COPY['product_description'])

    def test_flags_brands_affiliation_and_audit_leakage_without_export(self):
        draft = {**COPY, 'blocked_brands': ['Example Parts'],
                 'product_description': 'Factory-approved by Ｅｘａｍｐｌｅ–Parts. Unverified listing.',
                 'product_highlight': 'Nextworks fit. Confirm the mounting hole.',
                 'bullet_points': ['Check cable size', *COPY['bullet_points'][1:]]}
        result = self.run_cli(draft, '--blocked-brand', 'Nextworks', '--erp-fields', exit_code=1)
        self.assertEqual(result['brands_checked'], 2)
        self.assertEqual(set(result['issues']['product_description']),
                         {'brand_affiliation_language', 'blocked_brand', 'internal_audit_language'})
        self.assertIn('blocked_brand', result['issues']['product_highlight'])
        self.assertIn('repeated_purchase_reminders', result['issues']['all_copy'])
        self.assertNotIn('erp_fields', result)

    def test_enforces_unicode_bytes_and_field_shape(self):
        result = self.run_cli({**COPY, 'product_title': 'X' * 76, 'product_highlight': 'X' * 126,
                               'bullet_points': COPY['bullet_points'][:-1], 'backend_search_terms': 'é' * 125},
                              exit_code=1)
        self.assertEqual(result['backend_utf8_bytes'], 250)
        self.assertEqual(result['issues'], {'product_title': ['over_75_characters'],
                                           'product_highlight': ['over_125_characters'],
                                           'backend_search_terms': ['over_249_utf8_bytes'],
                                           'bullet_points': ['expected_five_bullets']})

    def test_hold_draft_can_be_checked_without_erp_export(self):
        result = self.run_cli({**COPY, 'status': 'HOLD'}, '--erp-fields')
        self.assertTrue(result['copy_checks_pass'])
        self.assertEqual(result['erp_fields_blocked'], 'HOLD')
        self.assertNotIn('erp_fields', result)
