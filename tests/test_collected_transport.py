"""Contract tests for the live commands. The subprocess never opens a socket."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


CLI = Path(__file__).resolve().parents[1] / 'scripts' / 'zhiying.py'
FIXTURE = """
import json
from pathlib import Path
import sys

state = Path(sys.argv[1])
log = Path(sys.argv[2])
behavior = sys.argv[3]
request = json.load(sys.stdin)
with log.open('a', encoding='utf-8') as output:
    output.write(json.dumps(request) + '\\n')
product = json.loads(state.read_text(encoding='utf-8'))
if request['command'] == 'spider.detail':
    print(json.dumps({'ok': True, 'record': product}))
elif any(product.get(key) != value for key, value in request['expected'].items()):
    print(json.dumps({'ok': False, 'error': 'conflict'}))
else:
    if behavior == 'save':
        product.update(request['fields'])
        state.write_text(json.dumps(product), encoding='utf-8')
    print(json.dumps({'ok': True}))
"""


class CollectedTransportTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        self.script, self.state, self.log = (root / name for name in ('transport.py', 'state.json', 'ops.jsonl'))
        self.script.write_text(FIXTURE, encoding='utf-8')
        self.intro = root / 'intro.txt'
        self.intro.write_text('A new product introduction.', encoding='utf-8')
        self.record = {'sale_id': 1001, 'sale_cur': 'USD', 'sale_intro': '{"en":"Old","zh":"Keep"}',
                       'sale_stock': '[{"key":"target","money":1.0},{"key":"other","money":2.0,"num":5}]'}
        self.state.write_text(json.dumps(self.record), encoding='utf-8')

    def cli(self, action, *options, transport=True, behavior='save', expected=0):
        env = os.environ.copy()
        env.pop('ZHIYING_COLLECTED_TRANSPORT', None)
        command = [sys.executable, str(CLI), f'collected-product-live-{action}', '--product-id', '1001']
        if transport:
            command.extend(['--transport', sys.executable,
                            '--transport-arg', str(self.script),
                            '--transport-arg', str(self.state),
                            '--transport-arg', str(self.log),
                            '--transport-arg', behavior])
        run = subprocess.run([*command, *map(str, options)], env=env, check=False,
                             capture_output=True, encoding='utf-8')
        self.assertEqual(run.returncode, expected, run.stderr + run.stdout)
        return json.loads(run.stdout)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_missing_transport_fails_with_no_fallback(self):
        result = self.cli('get', transport=False, expected=1)
        self.assertIn('Live TCP transport is not configured', result['error'])
        self.assertFalse(self.log.exists())

    def test_success_requires_update_and_separate_read_back(self):
        result = self.cli('edit', '--set-surcharge', 'target', '1.01', '--intro-file', self.intro)
        self.assertTrue(result['remote_read_back_verified'])
        self.assertEqual(result['transport_calls'], 3)
        read, write, verify = self.calls()
        self.assertEqual(read, {'command': 'spider.detail', 'id': 1001})
        self.assertEqual(verify, read)
        self.assertEqual(write['command'], 'spider.update')
        self.assertEqual(write['expected'], {key: self.record[key] for key in ('sale_intro', 'sale_stock')})
        self.assertEqual(set(write['fields']), {'sale_intro', 'sale_stock'})
        self.assertEqual(json.loads(write['fields']['sale_intro']), {'en': 'A new product introduction.', 'zh': 'Keep'})
        self.assertEqual(json.loads(write['fields']['sale_stock']),
                         [{'key': 'target', 'money': 1.01}, {'key': 'other', 'money': 2.0, 'num': 5}])

    def test_acknowledgement_without_read_back_match_fails_and_does_not_retry(self):
        result = self.cli('edit', '--set-surcharge', 'target', '1.01', behavior='ignore', expected=1)
        self.assertIn('read-back differs', result['error'])
        self.assertEqual([call['command'] for call in self.calls()],
                         ['spider.detail', 'spider.update', 'spider.detail'])

    def test_wrong_record_prevents_update(self):
        self.state.write_text(json.dumps({**self.record, 'sale_id': 1002}), encoding='utf-8')
        result = self.cli('edit', '--set-surcharge', 'target', '1.01', expected=1)
        self.assertIn('wrong product', result['error'])
        self.assertEqual(len(self.calls()), 1)


if __name__ == '__main__':
    unittest.main()
