"""Verify local credential storage and hidden-input failure behavior with synthetic data."""
import base64
import getpass
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import login_credentials as credentials
from erp_products import ProductError


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'private' / 'credentials.dpapi'
        self.secret = {'phone': '15500000000', 'password': 'Synthetic-only 密码 !'}

    def test_default_path_and_explicit_override(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.path.parent),
                                     'ZHIYING_CREDENTIAL_FILE': ''}):
            self.assertEqual(credentials.credential_path(), self.path.parent / 'ZhiYingSkill' / 'credentials.dpapi')
        with patch.dict(os.environ, {'ZHIYING_CREDENTIAL_FILE': str(self.path)}):
            self.assertEqual(credentials.credential_path(), self.path)

    def test_status_never_unlocks_or_returns_credentials(self):
        with patch.object(credentials, 'protect_bytes', return_value=b'synthetic-protected'):
            result = credentials.save_credentials(self.secret, self.path)
        with patch.object(credentials, 'unprotect_bytes', side_effect=AssertionError('Must not decrypt')):
            status = credentials.credential_status(self.path)
        self.assertTrue(status['credentials_saved'])
        self.assertFalse(status['credentials_verified'])
        for public in (result, status):
            encoded = json.dumps(public)
            self.assertNotIn(self.secret['phone'], encoded)
            self.assertNotIn(self.secret['password'], encoded)
        stored = self.path.read_bytes()
        self.assertNotIn(self.secret['phone'].encode(), stored)
        self.assertNotIn(self.secret['password'].encode(), stored)

    def test_failed_save_keeps_previous_encrypted_file(self):
        with patch.object(credentials, 'protect_bytes', return_value=b'old-protected'):
            credentials.save_credentials(self.secret, self.path)
        original = self.path.read_bytes()
        with patch.object(credentials, 'protect_bytes', return_value=b'new-protected'), \
                patch.object(credentials.os, 'replace', side_effect=OSError('secret from OS')):
            with self.assertRaises(ProductError) as error:
                credentials.save_credentials(self.secret, self.path)
        self.assertNotIn('secret from OS', str(error.exception))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_or_damaged_file_has_safe_failure(self):
        with self.assertRaises(ProductError):
            credentials.load_credentials(self.path)
        self.path.parent.mkdir()
        self.path.write_text('{"password":"must-not-be-output"}', encoding='utf-8')
        with self.assertRaises(ProductError) as error:
            credentials.credential_status(self.path)
        self.assertNotIn('must-not-be-output', str(error.exception))

    def test_noninteractive_input_is_rejected_before_prompt(self):
        with patch.object(credentials.sys.stdin, 'isatty', return_value=False), \
                patch('builtins.input', side_effect=AssertionError('Must not read')), \
                patch.object(credentials.getpass, 'getpass', side_effect=AssertionError('Must not read')):
            with self.assertRaises(ProductError):
                credentials.prompt_credentials()

    def test_getpass_echo_fallback_is_rejected(self):
        def fallback(*args, **kwargs):
            warnings.warn('Password input may echo', getpass.GetPassWarning)
            raise AssertionError('Fallback must stop at warning')
        with patch.object(credentials.sys.stdin, 'isatty', return_value=True), \
                patch.object(credentials.sys.stderr, 'isatty', return_value=True), \
                patch('builtins.input', return_value=self.secret['phone']), \
                patch.object(credentials.getpass, 'getpass', side_effect=fallback):
            with self.assertRaises(ProductError) as error:
                credentials.prompt_credentials()
        self.assertIn('cannot hide password input', str(error.exception))

    def test_hidden_input_preserves_password_whitespace(self):
        with patch.object(credentials.sys.stdin, 'isatty', return_value=True), \
                patch.object(credentials.sys.stderr, 'isatty', return_value=True), \
                patch('builtins.input', return_value=' 15500000000 '), \
                patch.object(credentials.getpass, 'getpass', return_value=' password '):
            entered = credentials.prompt_credentials()
        self.assertEqual(entered, {'phone': '15500000000', 'password': ' password '})

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI check')
    def test_real_dpapi_roundtrip_and_tamper_failure(self):
        result = credentials.save_credentials(self.secret, self.path)
        self.assertTrue(result['credentials_saved'])
        self.assertEqual(credentials.load_credentials(self.path), self.secret)
        original = self.path.read_bytes()
        self.assertNotIn(self.secret['phone'].encode(), original)
        self.assertNotIn(self.secret['password'].encode(), original)
        envelope = json.loads(original)
        protected = bytearray(base64.b64decode(envelope['data']))
        protected[-1] ^= 1
        envelope['data'] = base64.b64encode(protected).decode('ascii')
        self.path.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaises(ProductError):
            credentials.load_credentials(self.path)


if __name__ == '__main__':
    unittest.main()
