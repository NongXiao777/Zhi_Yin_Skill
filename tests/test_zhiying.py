import importlib.util
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('zhiying', ROOT / 'scripts' / 'zhiying.py')
zhiying = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zhiying)


class LocalProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def package(self, version):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'version': 'test-version'}))
            archive.writestr('assets/js/chunk-common.js',
                'baseUrl:"https://erp.zying.net/api",url:"/CmdHandler?cmd=order.view",method:"POST";'
                'baseUrl:"https://seller.zying.net/api",url:"/CmdHandler?cmd=plugin.select",method:"POST";')
        # Fake ZIP signatures in CRX headers must not affect payload selection.
        header_data = b'PK\x03\x04-header'
        if version == 3:
            prefix = b'Cr24' + struct.pack('<II', 3, len(header_data)) + header_data
        else:
            prefix = b'Cr24' + struct.pack('<III', 2, len(header_data), 2) + header_data + b'xx'
        path = self.root / ('extension-v%d.crx' % version)
        path.write_bytes(prefix + payload.getvalue())
        return path

    def test_crx_2_and_3_routes_are_read_without_header_confusion(self):
        for version in (2, 3):
            with self.subTest(version=version):
                result = zhiying.routes(self.package(version), '', 1)
                self.assertEqual(result['total_matches'], 2)
                self.assertEqual(result['returned'], 1)
                self.assertEqual(result['business_requests_sent'], 0)
                self.assertEqual(result['routes'][0]['effect'], 'unverified')

    def test_route_filter_limits_matching_command(self):
        result = zhiying.routes(self.package(3), 'ORDER', 10)
        self.assertEqual([r['command'] for r in result['routes']], ['order.view'])

    def test_report_summary_preserves_source_metric_and_limits_rows(self):
        report = json.loads((ROOT / 'examples' / 'sales-traffic.json').read_text(encoding='utf-8'))
        report['salesAndTrafficByAsin'][0]['trafficByAsin']['unitSessionPercentage'] = 12.5
        report['salesAndTrafficByAsin'][0].pop('sku')
        path = self.root / 'report.json'
        path.write_text(json.dumps(report), encoding='utf-8')
        result = zhiying.traffic_summary(path, 1)
        self.assertEqual(result['total_rows'], 2)
        self.assertEqual(result['returned'], 1)
        self.assertIsNone(result['rows'][0]['sku'])
        self.assertEqual(result['rows'][0]['unit_session_percentage'], 12.5)
        self.assertEqual(result['rows'][0]['sales'], 20)
        self.assertEqual(result['traffic_scope'], 'all_page_traffic_not_organic_attribution')

    def test_non_report_json_is_rejected(self):
        path = self.root / 'wrong.json'
        path.write_text('{"other": []}', encoding='utf-8')
        with self.assertRaises(ValueError):
            zhiying.traffic_summary(path, 10)

    def test_malformed_nested_report_shapes_are_rejected(self):
        values = [[], {'salesAndTrafficByAsin': [1]},
                  {'salesAndTrafficByAsin': [{'salesByAsin': [1]}]},
                  {'salesAndTrafficByAsin': [], 'reportSpecification': 'x'}]
        for value in values:
            with self.subTest(value=value):
                path = self.root / 'bad-shape.json'
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError):
                    zhiying.traffic_summary(path, 10)

    def test_invalid_manifest_and_cli_report_return_clear_errors(self):
        path = self.root / 'manifest.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('manifest.json', '[]')
        with self.assertRaises(ValueError):
            zhiying.archive_info(path)
        report = self.root / 'bad-report.json'
        report.write_text('[]', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'zhiying.py'),
            'traffic-summary', '--file', str(report)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
