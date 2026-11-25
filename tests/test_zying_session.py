import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('zying_session', ROOT / 'scripts' / 'zying_session.py')
zying_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zying_session)


class SessionTests(unittest.TestCase):
    def test_rejects_unprotected_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.json'
            path.write_text(json.dumps({'session_token': 'private'}), encoding='utf-8')
            with self.assertRaises(zying_session.SessionError):
                zying_session.load_session(path)

    def test_loads_only_the_decrypted_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.json'
            path.write_text(json.dumps({'format': 'zying-dpapi-session-v1', 'protected': 'YWJj'}),
                            encoding='utf-8')
            with patch.object(zying_session, '_unprotect', return_value=b'{"mode":"M"}') as decrypt:
                result = zying_session.load_session(path)
            decrypt.assert_called_once_with(b'abc')
            self.assertEqual(result, {'mode': 'M'})

    def test_invalid_ciphertext_fails_before_decrypting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.json'
            path.write_text(json.dumps({'format': 'zying-dpapi-session-v1', 'protected': '!'}),
                            encoding='utf-8')
            with patch.object(zying_session, '_unprotect') as decrypt:
                with self.assertRaises(zying_session.SessionError):
                    zying_session.load_session(path)
            decrypt.assert_not_called()

    def test_export_requires_explicit_diagnostics_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(zying_session.os, 'name', 'nt'), \
                    patch.object(zying_session.shutil, 'which', return_value='pwsh.exe'), \
                    patch.object(zying_session.subprocess, 'run') as run:
                with self.assertRaises(zying_session.SessionError):
                    zying_session.export_session(Path('client.exe'), Path('session.local.json'),
                                                deps_dir=temporary)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
