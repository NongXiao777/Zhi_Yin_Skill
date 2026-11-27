"""Read client fingerprints and locate possible native transport symbols."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


NATIVE = Path(__file__).resolve().parent / 'native'
DLL_KEYS = {
    'ZYing.Core.dll': 'core_sha256',
    'ZYing.Work.dll': 'work_sha256',
    'ZYing.User.dll': 'user_sha256',
}


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def inspect_symbols(directory, work_hash):
    if work_hash is None:
        return {'status': 'work_dll_unavailable'}
    shell = shutil.which('pwsh')
    if shell is None:
        return {'status': 'pwsh_required'}
    try:
        proc = subprocess.run(
            [shell, '-NoProfile', '-NonInteractive', '-File', str(NATIVE / 'Inspect.ps1'),
             '-AppDirectory', str(directory), '-RpcCandidates'],
            capture_output=True, timeout=30, check=True,
        )
        result = json.loads(proc.stdout.decode('utf-8-sig'))
        inspected_hash = result['work_sha256']
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {'status': 'inspection_failed'}
    if inspected_hash != work_hash:
        return {'status': 'work_dll_changed_during_diagnosis'}
    return result


def diagnose_client(app, baseline_name=None, symbols=False):
    profiles = json.loads((NATIVE / 'client-profiles.json').read_text(encoding='utf-8'))
    hashes, errors = {}, {}
    for dll in DLL_KEYS:
        try:
            hashes[dll] = fingerprint(app.parent / dll)
        except FileNotFoundError:
            errors[dll] = 'missing'
        except OSError:
            errors[dll] = 'unreadable'

    def match_count(profile):
        return sum(dll in hashes and hashes[dll] == profile[key] for dll, key in DLL_KEYS.items())

    exact = [profile for profile in profiles if match_count(profile) == len(DLL_KEYS)]
    matched = exact[0] if len(exact) == 1 else None
    if baseline_name is None:
        # Later entries are more recent and resolve ties between partial matches.
        baseline = matched or max(reversed(profiles), key=match_count)
    else:
        baseline = next((profile for profile in profiles if profile['name'] == baseline_name), None)
        if baseline is None:
            return {'ok': False, 'error': 'unknown_client_profile',
                    'available_profiles': [profile['name'] for profile in profiles]}

    expected = {dll: baseline[key] for dll, key in DLL_KEYS.items()}
    result = {
        'ok': True,
        'app': str(app),
        'supported': matched is not None,
        'matched_profile': matched['name'] if matched else None,
        'baseline_profile': baseline['name'],
        'baseline_rpc_type': baseline['rpc_type'],
        'dlls': {dll: errors.get(dll) or ('matched' if hashes[dll] == expected[dll] else 'changed')
                 for dll in DLL_KEYS},
        'sha256': {dll: hashes.get(dll) for dll in DLL_KEYS},
        'baseline_sha256': expected,
        'network_requests_sent': 0,
    }
    if symbols:
        result['rpc_inspection'] = inspect_symbols(app.parent, hashes.get('ZYing.Work.dll'))
    return result
