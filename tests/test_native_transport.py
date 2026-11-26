"""Opt-in checks against installed native DLLs, with synthetic loopback sessions."""
import json
import base64
import os
from pathlib import Path
import socket
import subprocess
import shutil
import struct
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from collected_transport import native_command
from login import save_session


# Build test records with the vendor's binary serializer, then let an independent
# loopback peer exercise the real response decoder. Every value is synthetic.
RECORD_FIXTURE = r'''
using System;
using System.IO;
using System.Reflection;
using System.Text.Json;
class Fixture {
  static int Main(string[] args) {
    AppDomain.CurrentDomain.AssemblyResolve += (s,e) => {
      var path=Path.Combine(args[0],new AssemblyName(e.Name).Name+".dll");
      return File.Exists(path) ? Assembly.LoadFrom(path) : null;
    };
    var core=Assembly.LoadFrom(Path.Combine(args[0],"ZYing.Core.dll"));
    var rt=core.GetType("ZYing.Data.Record",true);
    var rs=core.GetType("ZYing.Data.RecordSet",true);
    var records=Activator.CreateInstance(rs);
    using(var input=JsonDocument.Parse(Console.In.ReadToEnd())) {
      foreach(var row in input.RootElement.EnumerateObject()) {
        var record=rt.GetMethod("FromJson",new[]{typeof(string)}).Invoke(null,new object[]{row.Value.GetRawText()});
        rt.GetField("Name").SetValue(record,row.Name);
        rs.GetMethod("Add",new[]{rt}).Invoke(records,new[]{record});
      }
    }
    var bytes=(byte[])rs.GetMethod("ToBytes",Type.EmptyTypes).Invoke(records,null);
    Console.WriteLine(Convert.ToBase64String(bytes));
    return 0;
  }
}
'''


@unittest.skipUnless(os.environ.get('ZHIYING_NATIVE_TEST_APP'), 'Set ZHIYING_NATIVE_TEST_APP for native component checks')
class NativeTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = native_command(Path(os.environ['ZHIYING_NATIVE_TEST_APP']))
        cls.fixture_directory = TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        directory = Path(cls.fixture_directory.name)
        (directory / 'NativeTransport.cs').write_text(RECORD_FIXTURE, encoding='utf-8')
        shutil.copyfile(ROOT / 'scripts' / 'native' / 'Build.ps1', directory / 'Build.ps1')
        completed = subprocess.run([
            shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', str(directory / 'Build.ps1'),
            '-AppDirectory', cls.command[2], '-OutputDirectory', str(directory / 'bin'),
        ], capture_output=True, encoding='utf-8', timeout=30)
        result = json.loads(completed.stdout)
        if completed.returncode or not result.get('ok'):
            raise AssertionError('Synthetic record fixture did not compile')
        cls.fixture_command = [result['executable'], result['assembly'], result['app_directory']]

    def records(self, rows):
        result = subprocess.run(self.fixture_command, input=json.dumps(rows),
                                capture_output=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, 'Synthetic record serialization failed')
        return base64.b64decode(result.stdout.strip(), validate=True)

    def exchange(self, payload, rows, *, protected_session=None, rejected=False, message=''):
        record_bytes = self.records(rows)
        observed = {}
        with socket.socket() as listener, TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(8)
            address, port = listener.getsockname()
            env = os.environ.copy()
            env.pop('ZHIYING_SESSION_FILE', None)
            if protected_session is not None:
                session = dict(protected_session, server_address=address, server_port=port)
                target = save_session(session, Path(directory) / 'session.dpapi')
                self.assertNotIn(session['token'], target.read_text(encoding='utf-8'))
                env['ZHIYING_SESSION_FILE'] = str(target)
            else:
                payload = dict(payload, server_address=address, server_port=port)

            def read_exact(connection, count):
                buffer = bytearray()
                while len(buffer) < count:
                    part = connection.recv(count - len(buffer))
                    if not part:
                        raise AssertionError('Native request ended early')
                    buffer.extend(part)
                return bytes(buffer)

            def respond():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(8)
                        header = read_exact(connection, 5)
                        observed['marker'] = header[0]
                        length = int.from_bytes(header[1:], 'little')
                        if not 0 < length < 10000:
                            raise AssertionError('Unexpected native frame size')
                        request = read_exact(connection, length)
                        observed['request'] = request
                        text = message.encode('utf-8')
                        # Response identity uses the request's device and old token,
                        # followed by result, error flag, message, and binary records.
                        body = (struct.pack('<I', 0) + request[8:40] + struct.pack('<qB', 0, rejected)
                                + struct.pack('<i', len(text)) + text + record_bytes)
                        connection.sendall(b'c\0' + struct.pack('<I', len(body)) + body)
                except Exception as error:
                    observed['error'] = type(error).__name__

            worker = threading.Thread(target=respond, daemon=True)
            worker.start()
            completed = subprocess.run(self.command, input=json.dumps(payload), env=env,
                                       capture_output=True, encoding='utf-8', timeout=25)
            worker.join(timeout=3)
        self.assertNotIn('error', observed)
        return completed, observed, port

    def test_login_probe_encodes_synthetic_password_without_sending_a_request(self):
        result = subprocess.run(self.command, input='{"command":"login.probe"}',
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertTrue(data['password_was_encoded'])
        self.assertTrue(data['login_endpoint_resolved'])
        self.assertFalse(data['authenticated'])
        self.assertEqual(data['network_requests_sent'], 0)
        self.assertNotIn('synthetic-login', result.stdout)
        self.assertNotIn('session', data)

    def test_unrecognized_client_hash_stops_before_using_profile_symbols(self):
        with TemporaryDirectory() as directory:
            profiles = json.loads(Path(self.command[3]).read_text(encoding='utf-8'))
            for profile in profiles:
                profile['work_sha256'] = '0' * 64
            path = Path(directory) / 'profiles.json'
            path.write_text(json.dumps(profiles), encoding='utf-8')
            result = subprocess.run([*self.command[:3], str(path)], input='{"command":"login.probe"}',
                                    capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'unsupported_client_version'})
        self.assertNotIn('13800000000', result.stdout)

    def test_desktop_session_device_and_exchange_state_reach_the_native_frame(self):
        device = str(uuid.uuid4())
        result, observed, _ = self.exchange(
            {'command': 'spider.detail', 'id': 1001},
            {'root': {'sale_id': 1001, 'sale_cur': 'USD'}},
            protected_session={'token': str(uuid.uuid4()), 'user_id': 731,
                               'device_id': device, 'exchange_state': 789},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(observed['request'][8:24], uuid.UUID(device).bytes_le)
        self.assertEqual(struct.unpack('<i', observed['request'][:4])[0], 789)
        self.assertNotIn(device, result.stdout)

    def test_phone_login_extracts_only_a_confirmed_synthetic_session(self):
        token = str(uuid.uuid4())
        password = 'synthetic-login-秘密'
        result, observed, port = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': password},
            {'member': {'token': token, 'userid': 731, 'secret': 'unrelated-synthetic-secret'}},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertTrue(data['authenticated'])
        self.assertEqual(data['session'], {'server_address': '127.0.0.1', 'server_port': port,
                                          'token': token, 'user_id': 731})
        self.assertIn(b'common.login', observed['request'])
        self.assertIn(b'13800000000', observed['request'])
        self.assertNotIn(password.encode('utf-8'), observed['request'])
        self.assertEqual(observed['request'][24:40], bytes(16))
        self.assertNotIn('unrelated-synthetic-secret', result.stdout)
        self.assertEqual(set(data), {'ok', 'authenticated', 'session'})

    def test_login_does_not_claim_success_without_a_member_token(self):
        result, _, _ = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': 'synthetic-password'}, {},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'login_response_incomplete'})

    def test_login_stops_when_the_server_requires_a_password_change(self):
        result, _, _ = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': 'synthetic-password'},
            {'member': {'token': str(uuid.uuid4()), 'userid': 731}, 'force_pwd': {'force': 1}},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'password_change_required'})

    def test_login_does_not_accept_an_empty_response_token(self):
        result, _, _ = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': 'synthetic-password'},
            {'member': {'token': str(uuid.UUID(int=0)), 'userid': 731}},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'login_response_incomplete'})

    def test_rejected_login_does_not_print_a_server_echoed_secret(self):
        secret = 'synthetic-password-echo-in-server-message'
        result, _, _ = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': secret}, {},
            rejected=True, message=secret,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'login_rejected',
                                                   'reason': 'unclassified', 'server_result': 0})

    def test_rejected_login_classifies_reason_without_printing_echoed_credentials(self):
        secret = 'synthetic-password-echo'
        result, _, _ = self.exchange(
            {'command': 'common.login', 'phone': '13800000000', 'password': secret}, {},
            rejected=True, message='账号或密码错误: ' + secret,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data['reason'], 'credentials_rejected')
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_python_protected_session_is_unlocked_by_native_detail_transport(self):
        token = str(uuid.uuid4())
        result, observed, _ = self.exchange(
            {'command': 'spider.detail', 'id': 1001}, {'root': {'sale_id': 1001}},
            protected_session={'token': token, 'user_id': 731},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)['record']['sale_id'], 1001)
        self.assertEqual(observed['request'][24:40], uuid.UUID(token).bytes_le)

    def test_native_encoder_can_run_without_session_or_window(self):
        env = os.environ.copy()
        env.pop('ZHIYING_SESSION_FILE', None)
        result = subprocess.run(self.command, input='{"command":"native.probe"}',
                                env=env, capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertTrue(data['native_components_loaded'])
        self.assertGreater(data['request_bytes'], data['parameter_bytes'])
        self.assertEqual(data['network_requests_sent'], 0)

    def test_native_request_reaches_loopback_and_waits_for_a_valid_response(self):
        observed = {}
        received = threading.Event()
        release = threading.Event()
        with socket.socket() as listener, TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(8)

            def receive_exact(connection, count):
                chunks = bytearray()
                while len(chunks) < count:
                    part = connection.recv(count - len(chunks))
                    if not part:
                        raise AssertionError('Native request ended early')
                    chunks.extend(part)
                return bytes(chunks)

            def observe():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(5)
                        header = receive_exact(connection, 5)
                        observed['marker'] = header[0]
                        length = int.from_bytes(header[1:], 'little')
                        if not 0 < length < 10000:
                            raise AssertionError('Unexpected native frame size')
                        observed['payload'] = receive_exact(connection, length)
                        received.set()
                        release.wait(8)
                except Exception as error:
                    observed['error'] = type(error).__name__
                    received.set()

            worker = threading.Thread(target=observe, daemon=True)
            worker.start()
            session = Path(directory) / 'session.local.json'
            session.write_text(json.dumps({
                'server_address': '127.0.0.1', 'server_port': listener.getsockname()[1],
                'token': str(uuid.uuid4()),
            }), encoding='utf-8')
            env = os.environ.copy()
            env['ZHIYING_SESSION_FILE'] = str(session)
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env)
            try:
                process.stdin.write(b'{"command":"spider.detail","id":1001}')
                process.stdin.close()
                self.assertTrue(received.wait(8), 'The native request did not reach the loopback server')
                self.assertNotIn('error', observed)
                self.assertEqual(observed['marker'], 77)
                self.assertIn(b'spider.detail', observed['payload'])
                self.assertIn(b'1001', observed['payload'])
                self.assertIsNone(process.poll(), 'A detail read needs an actual response before returning')
            finally:
                if process.poll() is None:
                    process.kill()
                release.set()
                process.wait(timeout=5)
                stdout = process.stdout.read()
                process.stdout.close()
                process.stderr.close()
                worker.join(timeout=2)
            self.assertNotIn(b'"ok":true', stdout)


if __name__ == '__main__':
    unittest.main()
