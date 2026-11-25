"""Opt-in checks against installed native DLLs, with synthetic loopback sessions."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from collected_transport import native_command


@unittest.skipUnless(os.environ.get('ZHIYING_NATIVE_TEST_APP'), 'Set ZHIYING_NATIVE_TEST_APP for native component checks')
class NativeTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = native_command(Path(os.environ['ZHIYING_NATIVE_TEST_APP']))

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
