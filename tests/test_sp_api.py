import gzip
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sp_api
import zhiying


MARKET = 'ATVPDKIKX0DER'
MARKET_ARGS = ('--region', 'na', '--marketplace', MARKET)
REPORT_ARGS = ('--region', 'na', '--report-id', 'report-id')
REPORT_FILE = ROOT / 'examples' / 'sales-traffic.json'
CREDENTIALS = {
    'SP_API_CLIENT_ID': 'sample-client', 'SP_API_CLIENT_SECRET': 'sample-secret',
    'SP_API_REFRESH_TOKEN': 'sample-refresh', 'SP_API_SELLER_ID': 'A123TESTSELLER',
}
LWA = {'access_token': 'sample-access-token'}


def report_status(state, **fields):
    return {'reportType': sp_api.REPORT_TYPE, 'processingStatus': state, **fields}


class SellingPartnerCLITests(unittest.TestCase):
    def invoke(self, arguments, *responses, credentials=CREDENTIALS):
        opener = Mock()
        opener.open.side_effect = [response if isinstance(response, Exception) else io.BytesIO(
            response if isinstance(response, bytes) else json.dumps(response).encode('utf-8'))
            for response in responses]
        output = io.StringIO()
        with patch.dict('os.environ', credentials, clear=True), patch.object(sp_api, 'build_opener', return_value=opener):
            with patch.object(sys, 'argv', ['zhiying.py', *arguments]), redirect_stdout(output):
                status = zhiying.main()
        return status, json.loads(output.getvalue()), [call.args[0] for call in opener.open.call_args_list]

    def test_listing_reads_marketplace_offers_and_preserves_zero(self):
        payload = {
            'sku': 'a/b #', 'summaries': [{'marketplaceId': MARKET, 'asin': 'B000000001', 'status': ['BUYABLE']}],
            'offers': [
                {'marketplaceId': 'OTHER', 'price': {'currencyCode': 'CAD', 'amount': '99.00'}},
                {'marketplaceId': MARKET, 'price': {'currencyCode': 'USD', 'amount': '20.00'}},
            ],
            'fulfillmentAvailability': [{'fulfillmentChannelCode': 'DEFAULT', 'quantity': 0}],
        }
        code, output, calls = self.invoke(('listing-get', *MARKET_ARGS, '--sku', 'a/b #'), LWA, payload)
        self.assertEqual(code, 0)
        self.assertEqual(output['offers'][0]['amount'], '20.00')
        self.assertEqual(output['offer_count'], 1)
        self.assertEqual(output['availability'][0]['quantity'], 0)
        self.assertTrue(urlsplit(calls[1].full_url).path.endswith('/a%2Fb%20%23'))
        self.assertEqual(parse_qs(urlsplit(calls[1].full_url).query)['marketplaceIds'], [MARKET])

    def test_listing_preview_never_uses_publication_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'draft.json'
            arguments = ('listing-preview', *MARKET_ARGS, '--sku', 'SKU', '--file', str(path), '--limit', '1')
            path.write_text('{"productType":"PRODUCT","attributes":[]}', encoding='utf-8')
            code, output, calls = self.invoke(arguments)
            self.assertEqual((code, calls), (1, []))
            self.assertIn('attributes', output['error'])
            path.write_text('{"productType":"PRODUCT","attributes":{}}', encoding='utf-8-sig')
            issues = [{'code': '101', 'severity': 'ERROR', 'message': 'X' * 600}, {'code': '102'}]
            code, output, calls = self.invoke(arguments, LWA, {'status': 'INVALID', 'issues': issues})
        self.assertEqual(code, 0)
        self.assertEqual(output['status'], 'INVALID')
        self.assertEqual(output['issue_count'], 2)
        self.assertEqual(len(output['issues']), 1)
        self.assertEqual(len(output['issues'][0]['message']), 500)
        self.assertEqual(calls[1].get_method(), 'PUT')
        self.assertEqual(parse_qs(urlsplit(calls[1].full_url).query)['mode'], ['VALIDATION_PREVIEW'])
        self.assertEqual(json.loads(calls[1].data), {'productType': 'PRODUCT', 'attributes': {}})

    def test_fba_inventory_uses_sku_and_returns_inventory_details(self):
        inventory = {'payload': {'inventorySummaries': [{
            'sellerSku': 'SKU+1', 'fnSku': 'FNSKU', 'totalQuantity': 7, 'inventoryDetails': {
                'fulfillableQuantity': 0, 'inboundShippedQuantity': 4, 'reservedQuantity': {'totalReservedQuantity': 3},
            },
        }]}, 'pagination': {'nextToken': 'next+page'}}
        args = ('fba-inventory', *MARKET_ARGS, '--sku', 'SKU+1', '--next-token', 'first/page')
        code, output, calls = self.invoke(args, LWA, inventory)
        self.assertEqual(code, 0)
        self.assertEqual(output['rows'][0]['fulfillable'], 0)
        self.assertIsNone(output['rows'][0]['inbound_working'])
        self.assertEqual(output['rows'][0]['reserved'], 3)
        self.assertEqual(output['next_token'], 'next+page')
        query = parse_qs(urlsplit(calls[1].full_url).query)
        self.assertEqual(query['sellerSku'], ['SKU+1'])
        self.assertEqual(query['nextToken'], ['first/page'])

    def test_report_creation_is_bounded_to_sales_and_traffic(self):
        args = ('report-create', *MARKET_ARGS, '--start', '2025-10-01', '--end', '2025-10-02',
                '--asin-granularity', 'SKU')
        code, output, calls = self.invoke(args, LWA, {'reportId': 'report-id'})
        self.assertEqual(code, 0)
        self.assertEqual(output['report_id'], 'report-id')
        self.assertEqual(calls[1].get_method(), 'POST')
        self.assertEqual(json.loads(calls[1].data), {
            'reportType': sp_api.REPORT_TYPE, 'marketplaceIds': [MARKET],
            'dataStartTime': '2025-10-01T00:00:00Z', 'dataEndTime': '2025-10-02T23:59:59Z',
            'reportOptions': {'dateGranularity': 'DAY', 'asinGranularity': 'SKU'},
        })

    def test_report_summary_does_not_download_before_done_or_for_other_types(self):
        code, output, calls = self.invoke(('report-summary', *REPORT_ARGS), LWA, report_status('IN_PROGRESS'))
        self.assertEqual((code, len(calls)), (0, 2))
        self.assertFalse(output['ready'])
        unrelated = report_status('DONE', reportType='OTHER', reportDocumentId='doc')
        code, output, calls = self.invoke(('report-summary', *REPORT_ARGS), LWA, unrelated)
        self.assertEqual((code, len(calls)), (1, 2))
        self.assertIn('different', output['error'])

    def test_report_date_summary_downloads_gzip_without_lwa_or_signed_url_output(self):
        report = gzip.compress(REPORT_FILE.read_bytes())
        url = 'https://example.cloudfront.net/report?signature=sample-signature'
        document = {'url': url, 'compressionAlgorithm': 'GZIP'}
        args = ('report-summary', *REPORT_ARGS, '--by', 'date', '--sort', 'sessions', '--limit', '1')
        code, output, calls = self.invoke(args, LWA, report_status('DONE', reportDocumentId='doc'), document, report)
        self.assertEqual((code, len(calls)), (0, 4))
        self.assertTrue(output['ready'])
        self.assertEqual(output['rows'][0]['date'], '2026-11-02')
        self.assertEqual(output['rows'][0]['sessions'], 50)
        self.assertEqual(calls[1].get_header('X-amz-access-token'), LWA['access_token'])
        self.assertEqual(calls[2].get_header('X-amz-access-token'), LWA['access_token'])
        self.assertEqual(calls[3].full_url, url)
        self.assertIsNone(calls[3].get_header('X-amz-access-token'))
        self.assertNotIn('sample-signature', json.dumps(output))

    def test_invalid_document_host_and_missing_credentials_stop_before_requests(self):
        args = ('report-summary', *REPORT_ARGS)
        code, output, calls = self.invoke(args, credentials={})
        self.assertEqual((code, calls), (1, []))
        self.assertIn('SP_API_REFRESH_TOKEN', output['error'])
        document = {'url': 'https://example.cloudfront.net.example.org/report?signature=visible-in-input'}
        code, output, calls = self.invoke(args, LWA, report_status('DONE', reportDocumentId='doc'), document)
        self.assertEqual((code, len(calls)), (1, 3))
        self.assertNotIn('visible-in-input', output['error'])

    def test_http_errors_keep_status_and_request_id_without_raw_body(self):
        error = HTTPError('https://internal.example/', 429, 'private message', {'x-amzn-RequestId': 'request-123'},
                          io.BytesIO(b'private response'))
        code, output, calls = self.invoke(('report-status', *REPORT_ARGS), LWA, error)
        self.assertEqual((code, len(calls)), (1, 2))
        self.assertEqual(output['http_status'], 429)
        self.assertEqual(output['request_id'], 'request-123')
        self.assertNotIn('private', json.dumps(output))

    def test_local_summary_filters_and_sorts_before_limit(self):
        args = ('traffic-summary', '--file', str(REPORT_FILE), '--asin', 'b0test0000', '--sort', 'sessions', '--limit', '1')
        code, output, calls = self.invoke(args)
        self.assertEqual((code, calls), (0, []))
        self.assertEqual(output['business_requests_sent'], 0)
        self.assertEqual(output['matched_rows'], 2)
        self.assertEqual(output['rows'][0]['sku'], 'DEMO-002')
        args = ('traffic-summary', '--file', str(REPORT_FILE), '--sku', 'DEMO-002', '--limit', '1')
        code, output, _ = self.invoke(args)
        self.assertEqual(code, 0)
        self.assertEqual(output['matched_rows'], 1)
        self.assertEqual(output['rows'][0]['sku'], 'DEMO-002')
