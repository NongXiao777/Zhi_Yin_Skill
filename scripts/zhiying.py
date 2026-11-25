"""Compact ZYing diagnostics and Amazon seller operations."""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import date
from math import isfinite
from pathlib import Path


TRAFFIC_SORTS = ('source', 'sessions', 'units_ordered', 'unit_session_percentage')
COLLECTED_COMMANDS = ('collected-product-get', 'collected-product-edit')
LIVE_COLLECTED_COMMANDS = ('collected-product-live-get', 'collected-product-live-edit')
WINDOW_COMMANDS = ('window-status', 'window-focus')


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


def archive_info(path):
    if path.stat().st_size > 30_000_000:
        raise ValueError('Extension package exceeds the probe size limit')
    raw = path.read_bytes()
    if raw[:4] == b'Cr24':
        version = int.from_bytes(raw[4:8], 'little')
        if version == 3:
            offset = 12 + int.from_bytes(raw[8:12], 'little')
        elif version == 2:
            offset = 16 + int.from_bytes(raw[8:12], 'little') + int.from_bytes(raw[12:16], 'little')
        else:
            raise ValueError('Unsupported CRX version')
    else:
        offset = 0
    archive = zipfile.ZipFile(io.BytesIO(raw[offset:]))
    manifest = json.loads(archive.read('manifest.json'))
    if not isinstance(manifest, dict):
        archive.close()
        raise ValueError('Extension manifest must be a JSON object')
    return archive, manifest


def process_info(app):
    # Only select processes belonging to the named installation; omit command lines.
    escaped_root = str(app.parent).replace("'", "''")
    code = """
$ErrorActionPreference='Stop'
$taskRoot='%s'
$taskProcesses=@(Get-Process | Where-Object {
  $_.Path -and [IO.Path]::GetDirectoryName($_.Path) -eq $taskRoot -and
  ($_.ProcessName -like 'ZYing*' -or $_.ProcessName -eq 'CefSharp.BrowserSubprocess')
} | Select-Object Id,ProcessName)
$taskPorts=@()
if($taskProcesses.Count -gt 0){
  $taskPorts=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $taskProcesses.Id -contains $_.OwningProcess } |
    Select-Object LocalAddress,LocalPort,OwningProcess)
}
@{processes=$taskProcesses;listeners=$taskPorts} | ConvertTo-Json -Depth 4 -Compress
""" % escaped_root
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError('Windows process inspection failed')
    return json.loads(result.stdout.decode('utf-8-sig', errors='replace'))


def status(app, extension):
    result = {'installed': app.is_file(), 'app': str(app), 'extension_installed': extension.is_file()}
    if extension.is_file():
        archive, manifest = archive_info(extension)
        with archive:
            result['extension_version'] = manifest.get('version')
    if os.name == 'nt':
        result.update(process_info(app))
    else:
        result['process_check'] = 'Windows required'
    return result


def routes(extension, match, limit):
    archive, manifest = archive_info(extension)
    results = {}
    pattern = re.compile(r'baseUrl:"(?P<base>https://[a-z0-9.-]+\.zying\.net[^"\s]*)",url:"(?P<path>/[Cc]md[Hh]andler\?cmd=[A-Za-z0-9_.]+)",method:"(?P<method>[A-Z]+)"')
    with archive:
        names = [n for n in archive.namelist() if n.endswith(('chunk-common.js', 'background.js'))]
        for name in names:
            entry = archive.getinfo(name)
            if entry.file_size > 20_000_000:
                raise ValueError('Extension script exceeds the probe size limit')
            source = archive.read(name).decode('utf-8', errors='replace')
            for item in pattern.finditer(source):
                route = item.groupdict()
                cmd = route['path'].split('cmd=', 1)[1]
                if match and match.lower() not in cmd.lower():
                    continue
                key = (route['base'], route['path'], route['method'])
                results[key] = {'command': cmd, 'method': route['method'], 'url': route['base'] + route['path'],
                                'source': name, 'effect': 'unverified', 'payload_schema': 'unverified'}
    ordered = sorted(results.values(), key=lambda r: (r['command'], r['url']))
    return {'extension_version': manifest.get('version'), 'total_matches': len(ordered),
            'returned': min(limit, len(ordered)), 'routes': ordered[:limit], 'business_requests_sent': 0}


def launch(app, extension):
    if os.name != 'nt':
        raise RuntimeError('Launching this client requires Windows')
    if not app.is_file():
        raise FileNotFoundError('The installed client executable was not found')
    before = process_info(app)
    if before['processes']:
        return {'launch_requested': False, 'reason': 'already_running', **before}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    proc = subprocess.Popen([str(app)], cwd=str(app.parent), startupinfo=startup)
    time.sleep(2)
    observed = status(app, extension)
    return {'launch_requested': True, 'started_pid': proc.pid, 'launcher_exit_code': proc.poll(),
            'running_at_check': bool(observed.get('processes')), **observed}


def traffic_summary(path, limit, **options):
    if path.stat().st_size > 50_000_000:
        raise ValueError('Report exceeds the probe size limit')
    report = json.loads(path.read_text(encoding='utf-8-sig'))
    return {**summarize_traffic(report, limit, **options), 'business_requests_sent': 0}


def optional_object(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Report fields must contain JSON objects')
    return value


def traffic_row(row, by):
    sales = optional_object(row.get('salesByAsin' if by == 'asin' else 'salesByDate'))
    traffic = optional_object(row.get('trafficByAsin' if by == 'asin' else 'trafficByDate'))
    money = optional_object(sales.get('orderedProductSales'))
    identity = ({'sku': row.get('sku'), 'asin': row.get('childAsin') or row.get('parentAsin')}
                if by == 'asin' else {'date': row.get('date')})
    return {**identity, 'sessions': traffic.get('sessions'), 'page_views': traffic.get('pageViews'),
            'units_ordered': sales.get('unitsOrdered'), 'sales': money.get('amount'),
            'currency': money.get('currencyCode'), 'unit_session_percentage': traffic.get('unitSessionPercentage')}


def sortable_metric(row, field):
    value = row[field]
    if value is None:
        return (False, 0)
    if type(value) not in (int, float) or (isinstance(value, float) and not isfinite(value)):
        raise ValueError(f'Report field {field} must contain finite numbers')
    return (True, value)


def summarize_traffic(report, limit, *, by='asin', asin=None, sku=None, sort='source'):
    if not isinstance(report, dict):
        raise ValueError('Report must be a JSON object')
    if by == 'date' and (asin is not None or sku is not None):
        raise ValueError('ASIN and SKU filters require --by asin')
    rows = report.get('salesAndTrafficByAsin' if by == 'asin' else 'salesAndTrafficByDate')
    if not isinstance(rows, list):
        raise ValueError(f'Expected a Sales and Traffic JSON report with {by.upper()} rows')
    matched = 0
    selected = []
    filtered = asin is not None or sku is not None
    candidates = rows[:limit] if sort == 'source' and not filtered else rows
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError('Each report row must be a JSON object')
        if asin is not None and asin.upper() not in (row.get('childAsin'), row.get('parentAsin')):
            continue
        if sku is not None and sku != row.get('sku'):
            continue
        matched += 1
        if sort != 'source' or len(selected) < limit:
            selected.append(traffic_row(row, by))
    if sort != 'source':
        selected.sort(key=lambda row: sortable_metric(row, sort), reverse=True)
        selected = selected[:limit]
    specification = optional_object(report.get('reportSpecification'))
    result = {'report_type': specification.get('reportType'), 'start': specification.get('dataStartTime'),
              'end': specification.get('dataEndTime'), 'marketplaces': specification.get('marketplaceIds'),
              'traffic_scope': 'all_page_traffic_not_organic_attribution', 'total_rows': len(rows),
              'returned': len(selected), 'rows': selected, 'net_profit': 'requires_costs_and_fees'}
    if filtered:
        result['matched_rows'] = matched
    return result


def add_limit(parser):
    parser.add_argument('--limit', type=int, choices=range(1, 51), default=10, metavar='1..50')


def add_traffic_options(parser):
    parser.add_argument('--by', choices=('asin', 'date'), default='asin')
    parser.add_argument('--asin', help='match child or parent ASIN')
    parser.add_argument('--sku', help='match seller SKU exactly')
    parser.add_argument('--sort', choices=TRAFFIC_SORTS, default='source', help='numeric sorts are descending')
    add_limit(parser)


def traffic_options(args):
    if args.by == 'date' and (args.asin is not None or args.sku is not None):
        raise ValueError('ASIN and SKU filters require --by asin')
    return {'by': args.by, 'asin': args.asin, 'sku': args.sku, 'sort': args.sort}


def add_erp_commands(commands):
    source = argparse.ArgumentParser(add_help=False)
    source.add_argument('--file', type=Path, required=True, help='local CSV, TSV, JSON or XLSX product table')
    source.add_argument('--sheet', help='worksheet name for XLSX')
    selector = source.add_mutually_exclusive_group(required=True)
    selector.add_argument('--product-id', help='exact ERP product number')
    selector.add_argument('--parent-sku', help='exact parent SKU for tables grouped by SKU')
    source.add_argument('--price-column', help='explicit base price column header')
    add_limit(source)
    commands.add_parser('erp-product-get', parents=[source], help='select a product from a local table')
    preview = commands.add_parser('erp-draft-preview', parents=[source], help='preview package details and variant markup')
    rule = preview.add_mutually_exclusive_group()
    rule.add_argument('--add-amount', help='add this fixed amount to each variant')
    rule.add_argument('--markup-percent', help='add this percentage to each variant')
    preview.add_argument('--currency', help='expected currency, also used for rows without a currency')
    preview.add_argument('--decimals', type=int, choices=range(0, 5), default=2, help='price decimal places')
    preview.add_argument('--gross-weight-g', help='set package gross weight in grams for the selected rows')
    preview.add_argument('--package-cm', help='set package length x width x height in centimeters')
    preview.add_argument('--estimated-gross-weight-g', help='estimated gross weight for rows missing it')
    preview.add_argument('--estimated-package-cm', help='estimated package length x width x height for rows missing it')
    preview.add_argument('--estimate-basis', help='source and packing assumptions for the estimate')
    preview.add_argument('--output', type=Path, help='save the full review as a new JSON file')


def add_collected_commands(commands):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--product-id', required=True, help='expected sale_id')
    common.add_argument('--include-intro', action='store_true', help='include the full English introduction')
    common.add_argument('--include-copy', action='store_true', help='include available English listing fields')
    add_limit(common)
    local = argparse.ArgumentParser(add_help=False, parents=[common])
    local.add_argument('--file', type=Path, required=True, help='user-supplied collected-product JSON snapshot')
    remote = argparse.ArgumentParser(add_help=False, parents=[common])
    remote.add_argument('--transport', type=Path, help='authorized TCP transport executable')
    remote.add_argument('--transport-arg', action='append', default=[], help='transport argument, repeatable')
    edits = argparse.ArgumentParser(add_help=False)
    add_collected_edit_options(edits)
    commands.add_parser(COLLECTED_COMMANDS[0], parents=[local], help='read fields from a collected-product snapshot')
    local_edit = commands.add_parser(COLLECTED_COMMANDS[1], parents=[local, edits],
                                     help='preview or save a local snapshot edit')
    local_edit.add_argument('--output', type=Path, help='save and reread a new local JSON snapshot')
    commands.add_parser(LIVE_COLLECTED_COMMANDS[0], parents=[remote], help='read through an authorized transport')
    commands.add_parser(LIVE_COLLECTED_COMMANDS[1], parents=[remote, edits],
                        help='update through an authorized transport and read back the result')


def add_collected_edit_options(edit):
    edit.add_argument('--set-surcharge', action='append', nargs=2, default=[], metavar=('KEY', 'AMOUNT'),
                      help='set money for an exact variant key, repeatable')
    edit.add_argument('--adjust-surcharge', action='append', nargs=2, default=[], metavar=('KEY', 'DELTA'),
                      help='add a signed delta to money for an exact variant key, repeatable')
    edit.add_argument('--minimum-channel-price', help='quote a price ending in .49, .89 or .99 at or above this amount')
    edit.add_argument('--intro-file', type=Path, help='new English introduction as UTF-8 text')
    edit.add_argument('--copy-file', type=Path, help='UTF-8 JSON with the English listing fields to replace')
    edit.add_argument('--blocked-brand', action='append', default=[], help='brand name to exclude, repeatable')


def add_sp_api_commands(commands, regions):
    regional = argparse.ArgumentParser(add_help=False)
    regional.add_argument('--region', choices=regions, required=True)
    marketplace = argparse.ArgumentParser(add_help=False, parents=[regional])
    marketplace.add_argument('--marketplace', required=True, help='Amazon marketplace ID')
    listing = argparse.ArgumentParser(add_help=False, parents=[marketplace])
    listing.add_argument('--sku', required=True)
    add_limit(listing)
    commands.add_parser('listing-get', parents=[listing], help='read listing status, offers and availability')
    preview = commands.add_parser('listing-preview', parents=[listing], help='validate a listing draft with Amazon')
    preview.add_argument('--file', type=Path, required=True)
    inventory = commands.add_parser('fba-inventory', parents=[listing], help='read FBA stock for a SKU')
    inventory.add_argument('--next-token')
    create = commands.add_parser('report-create', parents=[marketplace], help='request a Sales and Traffic report')
    create.add_argument('--start', type=date.fromisoformat, required=True, metavar='YYYY-MM-DD')
    create.add_argument('--end', type=date.fromisoformat, required=True, metavar='YYYY-MM-DD')
    create.add_argument('--date-granularity', choices=('DAY', 'WEEK', 'MONTH'), default='DAY')
    create.add_argument('--asin-granularity', choices=('PARENT', 'CHILD', 'SKU'), default='CHILD')
    report = argparse.ArgumentParser(add_help=False, parents=[regional])
    report.add_argument('--report-id', required=True)
    commands.add_parser('report-status', parents=[report], help='check a Sales and Traffic report')
    summary = commands.add_parser('report-summary', parents=[report], help='download and summarize in memory')
    add_traffic_options(summary)


def sp_api_result(args, sp_api):
    api = sp_api.SellingPartnerAPI(args.region)
    if args.action == 'listing-get':
        return sp_api.get_listing(api, args.marketplace, args.sku, args.limit)
    if args.action == 'listing-preview':
        return sp_api.preview_listing(api, args.marketplace, args.sku, args.file, args.limit)
    if args.action == 'fba-inventory':
        return sp_api.fba_inventory(api, args.marketplace, args.sku, args.next_token, args.limit)
    if args.action == 'report-create':
        return sp_api.create_report(api, args.marketplace, args.start, args.end,
                                    args.date_granularity, args.asin_granularity)
    options = traffic_options(args) if args.action == 'report-summary' else None
    metadata, document_id = sp_api.report_status(api, args.report_id)
    if options is None or document_id is None:
        return metadata
    summary = summarize_traffic(api.report_document(document_id), args.limit, **options)
    return {**metadata, **{key: value for key, value in summary.items() if value is not None}}


def default_app():
    local = os.environ.get('LOCALAPPDATA')
    if local:
        app = Path(local) / 'Programs' / 'ZYing' / 'ZYing.exe'
        if app.is_file():
            return app
    return Path(r'D:\ZYing\ZYing.exe')


def main():
    import erp_products
    import listing_copy
    import sp_api

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=default_app())
    parser.add_argument('--extension', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', '.')) / 'ZYing' / 'zying-ext.crx')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('status', help='inspect local ZYing installation and processes')
    commands.add_parser('launch', help='start the installed ZYing client')
    commands.add_parser('collected-transport-probe', help='load native TCP components and encode an offline request')
    commands.add_parser('window-status')
    focus = commands.add_parser('window-focus')
    focus.add_argument('--window', type=int, help='Handle returned by window-status')
    route_parser = commands.add_parser('routes', help='inspect local extension route definitions')
    route_parser.add_argument('--match', default='')
    add_limit(route_parser)
    report_parser = commands.add_parser('traffic-summary', help='summarize a local Sales and Traffic JSON')
    report_parser.add_argument('--file', type=Path, required=True)
    add_traffic_options(report_parser)
    add_erp_commands(commands)
    add_collected_commands(commands)
    copy_check = commands.add_parser('listing-copy-check', help='check Amazon.com text and optionally map ERP fields')
    copy_check.add_argument('--file', type=Path, required=True)
    copy_check.add_argument('--blocked-brand', action='append', default=[], help='brand name to exclude, repeatable')
    copy_check.add_argument('--erp-fields', action='store_true', help='include the five ZYing ERP text fields on pass')
    add_sp_api_commands(commands, sp_api.REGIONS)
    args = parser.parse_args()
    args.app = args.app.resolve()
    args.extension = args.extension.resolve()
    try:
        if args.action == 'status':
            result = status(args.app, args.extension)
        elif args.action == 'launch':
            result = launch(args.app, args.extension)
        elif args.action == 'routes':
            result = routes(args.extension, args.match, args.limit)
        elif args.action in WINDOW_COMMANDS:
            from window_control import window_focus, window_status
            result = window_status(args.app) if args.action == 'window-status' else window_focus(args.app, args.window)
        elif args.action == 'collected-transport-probe':
            from collected_transport import native_probe
            result = native_probe(args.app)
        elif args.action in (*COLLECTED_COMMANDS, *LIVE_COLLECTED_COMMANDS):
            from collected_products import collected_result, encode_json
            from collected_transport import live_result
            if args.action in LIVE_COLLECTED_COMMANDS:
                result = live_result(args, edit=args.action == 'collected-product-live-edit')
            else:
                result = collected_result(args, edit=args.action == 'collected-product-edit')
            print(encode_json(result))
            return 0
        elif args.action == 'traffic-summary':
            result = traffic_summary(args.file, args.limit, **traffic_options(args))
        elif args.action in ('erp-product-get', 'erp-draft-preview'):
            result = erp_products.product_result(args, preview=args.action == 'erp-draft-preview')
        elif args.action == 'listing-copy-check':
            result = listing_copy.check_copy(args.file, args.blocked_brand, include_erp=args.erp_fields)
        else:
            result = sp_api_result(args, sp_api)
        emit(result)
        return int(result.get('ok') is False or (
            args.action == 'listing-copy-check' and not result['copy_checks_pass']))
    except (erp_products.ProductError, listing_copy.ListingCopyError) as error:
        emit({'ok': False, 'error': str(error)})
        return 1
    except sp_api.AmazonError as error:
        result = {'ok': False, 'error': str(error)}
        if error.http_status is not None:
            result['http_status'] = error.http_status
        if error.request_id is not None:
            result['request_id'] = error.request_id
        emit(result)
        return 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile, KeyError,
            TypeError, AttributeError):
        if args.action in ('status', 'launch', 'routes', 'collected-transport-probe', *WINDOW_COMMANDS):
            message = 'Probe failed. Verify the installation, package path and Windows process access.'
        elif args.action in ('traffic-summary', 'listing-preview', 'erp-product-get', 'erp-draft-preview',
                             'listing-copy-check', *COLLECTED_COMMANDS, *LIVE_COLLECTED_COMMANDS):
            message = 'Could not process the input. Check the file path, JSON contents and command options.'
        else:
            message = 'Could not process the Amazon response.'
        emit({'ok': False, 'error': message})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
