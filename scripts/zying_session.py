"""Export only ZYing's active native session using read-only ClrMD attachment.

The Windows user protects exported sessions with DPAPI. Secret GUIDs never appear
in the subprocess output. Microsoft ClrMD dependencies are supplied explicitly;
this helper does not download or execute client business assemblies.
"""

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class SessionError(RuntimeError):
    pass


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _unprotect(ciphertext):
    if os.name != 'nt':
        raise SessionError('DPAPI session loading requires Windows')
    buffer = (ctypes.c_ubyte * len(ciphertext)).from_buffer_copy(ciphertext)
    source = DataBlob(len(ciphertext), buffer)
    destination = DataBlob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None,
                                     1, ctypes.byref(destination)):
        raise SessionError('Cannot decrypt the session for this Windows user')
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel32.LocalFree(destination.data)


def load_session(path):
    envelope = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if envelope.get('format') != 'zying-dpapi-session-v1':
        raise SessionError('Unsupported session file format')
    try:
        data = _unprotect(base64.b64decode(envelope['protected'], validate=True))
        session = json.loads(data.decode('utf-8'))
    except (KeyError, ValueError, UnicodeError) as error:
        raise SessionError('Invalid protected session file') from error
    if not isinstance(session, dict):
        raise SessionError('Invalid session configuration')
    return session


def export_session(app, path, pid=None, *, deps_dir):
    if os.name != 'nt':
        raise SessionError('Session export requires Windows')
    shell = shutil.which('pwsh')
    if shell is None:
        raise SessionError('PowerShell 7 is required for ClrMD session export')
    diagnostics = Path(deps_dir).resolve()
    for relative in ('clrmd/lib/net6.0/Microsoft.Diagnostics.Runtime.dll',
                     'diag/lib/net6.0/Microsoft.Diagnostics.NETCore.Client.dll'):
        if not (diagnostics / relative).is_file():
            raise SessionError('Missing Microsoft diagnostics dependency: ' + relative)
    helper = Path(__file__).with_name('zying_session_export.ps1')
    arguments = [shell, '-NoProfile', '-NonInteractive', '-File', str(helper),
                 '-AppPath', str(Path(app).resolve()), '-OutputPath', str(Path(path).resolve()),
                 '-DiagnosticsDir', str(diagnostics)]
    if pid is not None:
        arguments.extend(['-ProcessId', str(pid)])
    result = subprocess.run(arguments, capture_output=True, timeout=30)
    try:
        report = json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError) as error:
        raise SessionError('Session helper did not return a valid status') from error
    if result.returncode or not report.get('ok'):
        raise SessionError(report.get('error', 'Session export failed'))
    return report


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diagnostics-dir', type=Path, required=True)
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    try:
        report = export_session(args.app, args.output, args.pid, deps_dir=args.diagnostics_dir)
        print(json.dumps(report, ensure_ascii=False, separators=(',', ':')))
        return 0
    except (SessionError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
