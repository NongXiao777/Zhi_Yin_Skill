"""Bounded Amazon SP-API operations for listings, FBA and Sales and Traffic."""
import gzip
import io
import json
import os
import re
import zlib
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


REGIONS = ('na', 'eu', 'fe')
REPORT_TYPE = 'GET_SALES_AND_TRAFFIC_REPORT'
REPORTS_API = '/reports/2021-06-30'
REPORT_LIMIT = 50_000_000
LISTING_REQUIREMENTS = ('LISTING', 'LISTING_PRODUCT_ONLY', 'LISTING_OFFER_ONLY')


class AmazonError(RuntimeError):
    def __init__(self, message, http_status=None, request_id=None):
        super().__init__(message)
        self.http_status = http_status
        self.request_id = request_id


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def read_bounded(stream, limit):
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise AmazonError('Amazon response exceeds the size limit')
    return raw


def json_object(raw, description):
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        raise AmazonError(f'Invalid JSON in {description}') from None
    if not isinstance(value, dict):
        raise AmazonError(f'Expected a JSON object in {description}')
    return value


def records(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise AmazonError('Unexpected array in Amazon response')
    return value


def fields(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AmazonError('Unexpected object in Amazon response')
    return value


def required_text(value, label):
    if not isinstance(value, str) or not value.strip() or value in ('.', '..'):
        raise AmazonError(f'Provide a valid {label}')
    return value


class SellingPartnerAPI:
    def __init__(self, region):
        if region not in REGIONS:
            raise AmazonError('Provide a valid SP-API region')
        self.base = f'https://sellingpartnerapi-{region}.amazon.com'
        self.opener = build_opener(NoRedirect())
        self.token = None

    def read(self, request, label, limit=5_000_000, *, compressed=False):
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = read_bounded(response, limit)
            if compressed:
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as decoded:
                    return read_bounded(decoded, limit)
            return raw
        except HTTPError as error:
            request_id = error.headers.get('x-amzn-RequestId', '') if error.headers else ''
            error.close()
            if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', request_id):
                request_id = None
            raise AmazonError(f'{label} returned HTTP {error.code}', error.code, request_id) from None
        except (URLError, OSError, HTTPException, EOFError, zlib.error):
            raise AmazonError(f'{label} could not be read') from None

    def access_token(self):
        if self.token is None:
            names = {
                'client_id': 'SP_API_CLIENT_ID',
                'client_secret': 'SP_API_CLIENT_SECRET',
                'refresh_token': 'SP_API_REFRESH_TOKEN',
            }
            values = {key: os.environ.get(name) for key, name in names.items()}
            missing = [names[key] for key, value in values.items() if not value or not value.strip()]
            if missing:
                raise AmazonError('Missing environment variables: ' + ', '.join(missing))
            body = urlencode({'grant_type': 'refresh_token', **values}).encode('ascii')
            request = Request('https://api.amazon.com/auth/o2/token', data=body, headers={
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                'Accept': 'application/json',
            })
            response = json_object(self.read(request, 'Amazon LWA', 65_536), 'Amazon LWA response')
            token = response.get('access_token')
            if not isinstance(token, str) or not re.fullmatch(r'[!-~]{1,4096}', token):
                raise AmazonError('Amazon LWA response is missing a valid access token')
            self.token = token
        return self.token

    def request(self, method, path, *, query=None, body=None):
        url = self.base + path
        if query:
            url += '?' + urlencode(query)
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'zhiying-cli/0.3.0 (Language=Python)',
            'x-amz-access-token': self.access_token(),
            'x-amz-date': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        }
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(url, data=data, headers=headers, method=method)
        return json_object(self.read(request, 'Amazon SP-API'), 'Amazon SP-API response')

    def report_document(self, document_id):
        meta = self.request('GET', f'{REPORTS_API}/documents/{quote(document_id, safe="")}')
        url = required_text(meta.get('url'), 'report document URL')
        try:
            parts = urlsplit(url)
            host = parts.hostname or ''
            valid = (parts.scheme == 'https' and not parts.username and not parts.password
                     and parts.port in (None, 443)
                     and host.endswith(('.cloudfront.net', '.amazonaws.com', '.amazonaws.com.cn')))
        except ValueError:
            valid = False
        if not valid:
            raise AmazonError('Unexpected Amazon report document host')
        compression = meta.get('compressionAlgorithm')
        if compression not in (None, 'GZIP'):
            raise AmazonError('Unsupported Amazon report compression')
        # Signed URL carries its own authorization. Never attach LWA headers or print it.
        request = Request(url, headers={'Accept-Encoding': 'identity'})
        raw = self.read(request, 'Amazon report document', REPORT_LIMIT, compressed=compression == 'GZIP')
        return json_object(raw, 'Amazon report document')


def marketplace_id(value):
    if not re.fullmatch(r'[A-Z0-9]{1,32}', value):
        raise AmazonError('Provide a valid Amazon marketplace ID')
    return value


def listing_path(sku):
    seller_id = os.environ.get('SP_API_SELLER_ID', '')
    if not re.fullmatch(r'[A-Z0-9]{1,32}', seller_id):
        raise AmazonError('Set SP_API_SELLER_ID to the Amazon seller ID')
    return f'/listings/2021-08-01/items/{seller_id}/{quote(required_text(sku, "SKU"), safe="")}'


def listing_issues(response, limit):
    issues = records(response.get('issues', []))
    return {
        'issue_count': len(issues),
        'issues': [{
            'code': item.get('code'),
            'severity': item.get('severity'),
            'message': (item.get('message') or '')[:500],
            'attributes': (item.get('attributeNames') or [])[:10],
        } for item in issues[:limit]],
    }


def get_listing(api, marketplace, sku, limit):
    marketplace = marketplace_id(marketplace)
    response = api.request('GET', listing_path(sku), query={
        'marketplaceIds': marketplace,
        'includedData': 'summaries,offers,fulfillmentAvailability,issues',
    })
    summary = next((row for row in records(response.get('summaries', []))
                    if row.get('marketplaceId') == marketplace), {})
    offers = [row for row in records(response.get('offers', [])) if row.get('marketplaceId') == marketplace]
    availability = records(response.get('fulfillmentAvailability', []))
    prices = []
    for offer in offers[:limit]:
        price = fields(offer.get('price'))
        prices.append({'type': offer.get('offerType'), 'audience': fields(offer.get('audience')).get('value'),
                       'amount': price.get('amount'), 'currency': price.get('currencyCode')})
    return {
        'sku': response.get('sku', sku), 'marketplace': marketplace,
        'asin': summary.get('asin'), 'status': summary.get('status'), 'product_type': summary.get('productType'),
        'offer_count': len(offers), 'offers': prices,
        'availability_count': len(availability),
        'availability': [{'channel': row.get('fulfillmentChannelCode'), 'quantity': row.get('quantity')}
                         for row in availability[:limit]],
        **listing_issues(response, limit),
    }


def preview_listing(api, marketplace, sku, path, limit):
    if path.stat().st_size > 1_000_000:
        raise AmazonError('Listing draft exceeds the size limit')
    body = json_object(path.read_bytes(), 'listing draft')
    required_text(body.get('productType'), 'draft productType')
    if not isinstance(body.get('attributes'), dict):
        raise AmazonError('Draft attributes must be a JSON object')
    if 'requirements' in body and body['requirements'] not in LISTING_REQUIREMENTS:
        raise AmazonError('Invalid listing draft requirements value')
    if body.keys() - {'productType', 'attributes', 'requirements'}:
        raise AmazonError('Draft contains unexpected top-level fields')
    response = api.request('PUT', listing_path(sku), body=body, query={
        'marketplaceIds': marketplace_id(marketplace), 'mode': 'VALIDATION_PREVIEW', 'includedData': 'issues',
    })
    return {
        'sku': response.get('sku', sku), 'marketplace': marketplace, 'mode': 'VALIDATION_PREVIEW',
        'status': response.get('status'), **listing_issues(response, limit),
    }


def fba_inventory(api, marketplace, sku, next_token, limit):
    marketplace = marketplace_id(marketplace)
    query = {
        'granularityType': 'Marketplace', 'granularityId': marketplace, 'marketplaceIds': marketplace,
        'details': 'true', 'sellerSku': required_text(sku, 'SKU'),
    }
    if next_token:
        query['nextToken'] = next_token
    response = api.request('GET', '/fba/inventory/v1/summaries', query=query)
    inventory = records(fields(response.get('payload')).get('inventorySummaries'))
    rows = []
    for item in inventory[:limit]:
        detail = fields(item.get('inventoryDetails'))
        rows.append({
            'sku': item.get('sellerSku'), 'asin': item.get('asin'), 'fnsku': item.get('fnSku'),
            'condition': item.get('condition'), 'updated': item.get('lastUpdatedTime'),
            'total': item.get('totalQuantity'), 'fulfillable': detail.get('fulfillableQuantity'),
            'inbound_working': detail.get('inboundWorkingQuantity'),
            'inbound_shipped': detail.get('inboundShippedQuantity'),
            'inbound_receiving': detail.get('inboundReceivingQuantity'),
            'reserved': fields(detail.get('reservedQuantity')).get('totalReservedQuantity'),
        })
    return {'marketplace': marketplace, 'sku': sku, 'page_rows': len(inventory), 'rows': rows,
            'next_token': fields(response.get('pagination')).get('nextToken')}


def create_report(api, marketplace, start, end, date_granularity, asin_granularity):
    now = datetime.now(timezone.utc)
    if start > end or end > now.date():
        raise AmazonError('Report dates must be in order and no later than today (UTC)')
    end_time = now.strftime('%Y-%m-%dT%H:%M:%SZ') if end == now.date() else f'{end.isoformat()}T23:59:59Z'
    response = api.request('POST', f'{REPORTS_API}/reports', body={
        'reportType': REPORT_TYPE, 'marketplaceIds': [marketplace_id(marketplace)],
        'dataStartTime': f'{start.isoformat()}T00:00:00Z', 'dataEndTime': end_time,
        'reportOptions': {'dateGranularity': date_granularity, 'asinGranularity': asin_granularity},
    })
    return {'report_id': required_text(response.get('reportId'), 'report ID returned by Amazon'),
            'report_type': REPORT_TYPE, 'marketplace': marketplace}


def report_status(api, report_id):
    report_id = required_text(report_id, 'report ID')
    response = api.request('GET', f'{REPORTS_API}/reports/{quote(report_id, safe="")}')
    if response.get('reportType') != REPORT_TYPE:
        raise AmazonError('The report ID is for a different Amazon report type')
    state = required_text(response.get('processingStatus'), 'report processing status returned by Amazon')
    document_id = response.get('reportDocumentId') if state == 'DONE' else None
    if state == 'DONE':
        required_text(document_id, 'report document ID returned by Amazon')
    return {
        'report_id': report_id, 'report_type': REPORT_TYPE, 'processing_status': state,
        'ready': document_id is not None, 'start': response.get('dataStartTime'), 'end': response.get('dataEndTime'),
        'marketplaces': response.get('marketplaceIds'),
    }, document_id
