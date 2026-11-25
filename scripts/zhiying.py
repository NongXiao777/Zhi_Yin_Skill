"""Compact, credential-free local probe for the installed ZYing client."""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


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


def traffic_summary(path, limit):
    if path.stat().st_size > 50_000_000:
        raise ValueError('Report exceeds the probe size limit')
    report = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(report, dict):
        raise ValueError('Report must be a JSON object')
    rows = report.get('salesAndTrafficByAsin')
    if not isinstance(rows, list):
        raise ValueError('Expected a Sales and Traffic JSON report with ASIN rows')
    selected = []
    def optional_object(value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError('Report fields must contain JSON objects')
        return value
    for row in rows[:limit]:
        if not isinstance(row, dict):
            raise ValueError('Each ASIN row must be a JSON object')
        sales = optional_object(row.get('salesByAsin'))
        traffic = optional_object(row.get('trafficByAsin'))
        money = optional_object(sales.get('orderedProductSales'))
        selected.append({'sku': row.get('sku'), 'asin': row.get('childAsin') or row.get('parentAsin'),
                         'sessions': traffic.get('sessions'), 'page_views': traffic.get('pageViews'),
                         'units_ordered': sales.get('unitsOrdered'), 'sales': money.get('amount'),
                         'currency': money.get('currencyCode'),
                         'unit_session_percentage': traffic.get('unitSessionPercentage')})
    specification = optional_object(report.get('reportSpecification'))
    return {'report_type': specification.get('reportType'), 'start': specification.get('dataStartTime'),
            'end': specification.get('dataEndTime'), 'marketplaces': specification.get('marketplaceIds'),
            'traffic_scope': 'all_page_traffic_not_organic_attribution', 'total_rows': len(rows),
            'returned': len(selected), 'rows': selected,
            'net_profit': 'requires_costs_and_fees', 'business_requests_sent': 0}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path(r'D:\ZYing\ZYing.exe'))
    parser.add_argument('--extension', type=Path,
                        default=Path(os.environ.get('LOCALAPPDATA', '.')) / 'ZYing' / 'zying-ext.crx')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('status')
    commands.add_parser('launch')
    commands.add_parser('window-status')
    focus_parser = commands.add_parser('window-focus')
    focus_parser.add_argument('--window', type=int, help='Handle returned by window-status')
    route_parser = commands.add_parser('routes')
    route_parser.add_argument('--match', default='')
    route_parser.add_argument('--limit', type=int, choices=range(1, 51), default=10, metavar='1..50')
    report_parser = commands.add_parser('traffic-summary')
    report_parser.add_argument('--file', type=Path, required=True)
    report_parser.add_argument('--limit', type=int, choices=range(1, 51), default=10, metavar='1..50')
    import product_cli
    product_cli.add_commands(commands)
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
        elif args.action == 'window-status':
            from window_control import window_status
            result = window_status(args.app)
        elif args.action == 'window-focus':
            from window_control import window_focus
            result = window_focus(args.app, args.window)
        elif args.action.startswith('product-') or args.action == 'session-export':
            result = product_cli.run(args)
        else:
            result = traffic_summary(args.file.resolve(), args.limit)
        emit(result)
        return 1 if result.get('ok') is False else 0
    except product_cli.ProductDataError as error:
        emit({'ok': False, 'error_type': 'product_data', 'error': str(error)})
        return 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile, KeyError) as error:
        if args.action.startswith('product-') or args.action == 'session-export':
            from zying_session import SessionError
            from zying_transport import ProtocolError, ServerError
            if isinstance(error, ServerError):
                emit({'ok': False, 'error_type': 'server', 'result': error.result,
                      'error': str(error)})
            elif isinstance(error, (ProtocolError, SessionError)):
                emit({'ok': False, 'error_type': type(error).__name__, 'error': str(error)})
            else:
                emit({'ok': False, 'error_type': 'io',
                      'error': 'Product operation could not complete; inspect the saved plan before replaying'})
            return 1
        emit({'ok': False, 'error': 'Probe failed; verify the installation, package path and Windows process access'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
