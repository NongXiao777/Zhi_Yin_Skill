"""Exercise the login command with synthetic native replies and protected temporary files."""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import collected_transport
import login
import login_credentials
import zhiying
from erp_products import ProductError


class LoginTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.session_file = self.root / 'session.dpapi'
        self.credential_file = self.root / 'credentials.dpapi'
        self.secret = {'phone': '15500000000', 'password': 'Synthetic-only 密码 !'}
        self.session = {'server_address': '127.0.0.1', 'server_port': 43210,
                        'token': 'e8277df5-408a-4f8e-8d35-e0955df916c6', 'user_id': 123}
        self.args = SimpleNamespace(action='login', app=self.root / 'ZYing.exe',
                                    saved=False, remember=False, credential_file=self.credential_file,
                                    session_file=self.session_file, server_address=None, server_port=None)
        self.transport = ['synthetic-dotnet.exe', 'NativeTransport.dll', str(self.root)]

    def response(self):
        return {'ok': True, 'authenticated': True, 'session': deepcopy(self.session),
                'debug_password': self.secret['password'], 'debug_phone': self.secret['phone']}

    def assert_safe(self, output):
        text = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
        for secret in (*self.secret.values(), self.session['token']):
            self.assertNotIn(secret, text)

    def invoke(self, response=None, *, remember=False):
        self.args.remember = remember
        entered = deepcopy(self.secret)
        with patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login.credentials, 'prompt_credentials', return_value=entered), \
                patch.object(login, 'request', return_value=response or self.response()), \
                patch.object(login.credentials, 'protect_bytes', return_value=b'synthetic-encrypted-session'):
            result = login.login_result(self.args)
        self.assertEqual(entered, {}, 'The local credential dictionary must be released after use')
        return result

    def test_success_returns_only_safe_fields_and_protects_session(self):
        result = self.invoke()
        self.assertTrue(result['authenticated'])
        self.assertTrue(result['session_saved'])
        self.assertEqual(result['session_file'], str(self.session_file))
        self.assert_safe(result)
        saved = self.session_file.read_bytes()
        self.assert_safe(saved.decode())
        envelope = json.loads(saved)
        self.assertEqual(envelope['purpose'], login.SESSION_PURPOSE)
        self.assertEqual(envelope['protection'], login_credentials.PROTECTION)

    def test_desktop_session_identity_is_preserved_when_protected(self):
        session = {**self.session, 'device_id': '02a6e9e4-9102-4935-a366-32f0b8c0aba2',
                   'exchange_state': 789}
        self.assertEqual(login._validated_session(session), session)
        for changes in ({'device_id': str(__import__('uuid').UUID(int=0))},
                        {'exchange_state': True}, {'exchange_state': 2147483648}):
            with self.assertRaises(ProductError):
                login._validated_session({**session, **changes})

    def test_secrets_go_to_private_stdin_and_never_subprocess_arguments(self):
        entered = deepcopy(self.secret)
        native_reply = json.dumps(self.response(), ensure_ascii=False).encode('utf-8')
        completed = subprocess.CompletedProcess(self.transport, 0, native_reply, b'synthetic stderr')
        with patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login.credentials, 'prompt_credentials', return_value=entered), \
                patch.object(collected_transport.subprocess, 'run', return_value=completed) as run, \
                patch.object(login.credentials, 'protect_bytes', return_value=b'synthetic-ciphertext'):
            result = login.login_result(self.args)
        call = run.call_args
        self.assertEqual(call.args[0], self.transport)
        self.assert_safe(json.dumps(call.args[0]))
        self.assertTrue(call.kwargs['capture_output'])
        payload = json.loads(call.kwargs['input'])
        self.assertEqual(payload, {'command': 'common.login', **self.secret})
        self.assert_safe(result)

    def test_invalid_or_unconfirmed_reply_does_not_create_or_replace_session(self):
        invalid_sessions = [None, {}, {**self.session, 'token': '00000000-0000-0000-0000-000000000000'},
                            {**self.session, 'server_port': True}, {**self.session, 'user_id': 0},
                            {**self.session, 'server_address': 'not-an-ip'}]
        replies = [{'ok': True, 'authenticated': False, 'session': self.session}]
        replies.extend({'ok': True, 'authenticated': True, 'session': session} for session in invalid_sessions)
        for existing in (False, True):
            for reply in replies:
                with self.subTest(existing=existing, reply=reply):
                    self.session_file.unlink(missing_ok=True)
                    if existing:
                        self.session_file.write_bytes(b'old-protected-session')
                    with self.assertRaises(ProductError):
                        self.invoke(reply)
                    self.assertEqual(self.session_file.exists(), existing)
                    if existing:
                        self.assertEqual(self.session_file.read_bytes(), b'old-protected-session')

    def test_rejected_login_and_native_errors_leave_old_session_untouched(self):
        self.session_file.write_bytes(b'old-protected-session')
        entered = deepcopy(self.secret)
        with patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login.credentials, 'prompt_credentials', return_value=entered), \
                patch.object(login, 'request', side_effect=ProductError('Login was rejected.')):
            with self.assertRaises(ProductError):
                login.login_result(self.args)
        self.assertEqual(self.session_file.read_bytes(), b'old-protected-session')
        self.assertEqual(entered, {})

    def test_session_save_failure_preserves_previous_file(self):
        self.session_file.write_bytes(b'old-protected-session')
        entered = deepcopy(self.secret)
        with patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login.credentials, 'prompt_credentials', return_value=entered), \
                patch.object(login, 'request', return_value=self.response()), \
                patch.object(login.credentials, 'protect_bytes', return_value=b'new-encrypted-session'), \
                patch.object(login.credentials.os, 'replace', side_effect=OSError('synthetic write error')):
            with self.assertRaises(ProductError):
                login.login_result(self.args)
        self.assertEqual(self.session_file.read_bytes(), b'old-protected-session')
        self.assertEqual(list(self.root.iterdir()), [self.session_file])

    def test_remember_failure_reports_successful_login_and_preserves_credentials(self):
        self.credential_file.write_bytes(b'old-protected-credentials')
        with patch.object(login.credentials, 'save_credentials', side_effect=ProductError('Synthetic storage failure.')):
            result = self.invoke(remember=True)
        self.assertTrue(result['authenticated'])
        self.assertTrue(result['session_saved'])
        self.assertFalse(result['credentials_saved'])
        self.assertTrue(result['credential_save_failed'])
        self.assertEqual(self.credential_file.read_bytes(), b'old-protected-credentials')
        self.assert_safe(result)

    def test_saved_credentials_are_loaded_once_and_never_prompted(self):
        self.args.saved = True
        entered = deepcopy(self.secret)
        with patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login.credentials, 'load_credentials', return_value=entered) as load, \
                patch.object(login.credentials, 'prompt_credentials', side_effect=AssertionError('Must not prompt')), \
                patch.object(login, 'request', return_value=self.response()), \
                patch.object(login.credentials, 'protect_bytes', return_value=b'synthetic-ciphertext'):
            result = login.login_result(self.args)
        load.assert_called_once_with(self.credential_file)
        self.assertEqual(entered, {})
        self.assert_safe(result)

    def test_noninteractive_cli_rejects_before_login_or_secret_output(self):
        output = io.StringIO()
        argv = [str(ROOT / 'scripts' / 'zhiying.py'), '--app', str(self.args.app), 'login',
                '--session-file', str(self.session_file)]
        with patch.object(sys, 'argv', argv), patch.object(sys, 'stdout', output), \
                patch.object(sys.stdin, 'isatty', return_value=False), \
                patch.object(login, 'native_command', return_value=self.transport), \
                patch.object(login, 'request', side_effect=AssertionError('Must not send login')):
            exit_code = zhiying.main()
        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(result['ok'])
        self.assertIn('interactive terminal', result['error'])
        self.assertFalse(self.session_file.exists())
        self.assert_safe(output.getvalue())

    def test_native_failure_stdout_and_stderr_do_not_reach_cli_error(self):
        raw = json.dumps({'ok': False, 'error': self.secret['password'],
                          'token': self.session['token']}).encode('utf-8')
        completed = subprocess.CompletedProcess(self.transport, 1, raw, self.secret['phone'].encode())
        with patch.object(collected_transport.subprocess, 'run', return_value=completed):
            with self.assertRaises(ProductError) as error:
                collected_transport.request(self.transport, {'command': 'common.login', **self.secret})
        self.assert_safe(str(error.exception))

    def test_default_session_can_be_selected_by_business_transport(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.root), 'ZHIYING_SESSION_FILE': '',
                                     'ZHIYING_COLLECTED_TRANSPORT': ''}):
            target = login.session_path()
            self.assertEqual(target, self.root / 'ZhiYingSkill' / 'session.dpapi')
            with patch.object(login.credentials, 'protect_bytes', return_value=b'synthetic-ciphertext'):
                login.save_session(self.session)
            args = SimpleNamespace(app=self.args.app, transport=None, transport_arg=[])
            with patch.object(collected_transport, 'native_command', return_value=self.transport):
                self.assertEqual(collected_transport.transport_command(args), self.transport)
            with patch.object(login.credentials, 'unprotect_bytes', side_effect=AssertionError('Must not unlock')):
                result = login.login_status()
            self.assertTrue(result['session_saved'])
            self.assertFalse(result['session_verified'])
            self.assert_safe(result)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI check')
    def test_session_envelope_roundtrips_real_current_user_dpapi(self):
        target = login.save_session(self.session, self.session_file)
        envelope = json.loads(target.read_text(encoding='utf-8'))
        plaintext = login_credentials.unprotect_bytes(base64.b64decode(envelope['data']))
        self.assertEqual(json.loads(plaintext), self.session)
        self.assert_safe(target.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
