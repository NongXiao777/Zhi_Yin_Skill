"""Collect login credentials in a terminal and protect them with user-bound DPAPI."""
import base64
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import warnings

from erp_products import ProductError


CREDENTIAL_ENV = 'ZHIYING_CREDENTIAL_FILE'
PROTECTION = 'windows-dpapi-current-user'
PURPOSE = 'zhiying-login-credentials'
FILE_LIMIT = 65536
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, *, decrypt):
    if os.name != 'nt':
        raise ProductError('Local credential protection requires Windows DPAPI.')
    if not isinstance(data, bytes) or not data or len(data) > FILE_LIMIT:
        raise ProductError('Invalid data for local credential protection.')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    description = ctypes.c_void_p()
    try:
        if decrypt:
            function = crypt.CryptUnprotectData
            function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_void_p),
                                 ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.POINTER(_DataBlob)]
            function.restype = wintypes.BOOL
            success = function(ctypes.byref(source), ctypes.byref(description), None, None,
                               None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target))
        else:
            function = crypt.CryptProtectData
            function.argtypes = [ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
                                 ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.POINTER(_DataBlob)]
            function.restype = wintypes.BOOL
            success = function(ctypes.byref(source), 'ZhiYing Skill', None, None, None,
                               CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target))
        if not success or not target.pbData or not 0 < target.cbData <= FILE_LIMIT:
            raise ProductError('Could not protect or unlock the local credentials with this Windows user.')
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.memset(source_buffer, 0, len(data))
        if target.pbData:
            if decrypt and target.cbData:
                ctypes.memset(target.pbData, 0, target.cbData)
            kernel.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))
        if description.value:
            kernel.LocalFree(description)


def protect_bytes(data):
    return _dpapi(data, decrypt=False)


def unprotect_bytes(data):
    return _dpapi(data, decrypt=True)


def credential_path(path=None):
    selected = path or os.environ.get(CREDENTIAL_ENV)
    if selected:
        return Path(selected).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise ProductError('Set LOCALAPPDATA or ZHIYING_CREDENTIAL_FILE for local credential storage.')
    return Path(local).resolve() / 'ZhiYingSkill' / 'credentials.dpapi'


def _validate_credentials(credentials):
    if not isinstance(credentials, dict):
        raise ProductError('The login credentials are invalid.')
    phone = credentials.get('phone')
    password = credentials.get('password')
    if not isinstance(phone, str) or not re.fullmatch(r'\+?[0-9]{6,20}', phone):
        raise ProductError('Enter the phone number using digits, optionally prefixed with +.')
    if not isinstance(password, str) or not 0 < len(password) <= 4096 or '\0' in password:
        raise ProductError('Enter a nonempty password of at most 4096 characters.')
    return {'phone': phone, 'password': password}


def prompt_credentials():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ProductError('Open an interactive terminal to enter the phone number and hidden password.')
    try:
        phone = input('手机号: ').strip()
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('密码（隐藏输入）: ', stream=sys.stderr)
    except getpass.GetPassWarning:
        raise ProductError('This terminal cannot hide password input. Use a Windows console.') from None
    except (EOFError, KeyboardInterrupt):
        raise ProductError('Credential entry was cancelled.') from None
    return _validate_credentials({'phone': phone, 'password': password})


def _atomic_write(path, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.credentials-', delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise ProductError('Could not save the protected local credential file.') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def save_credentials(credentials, path=None):
    credentials = _validate_credentials(credentials)
    target = credential_path(path)
    plaintext = json.dumps(credentials, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    protected = protect_bytes(plaintext)
    envelope = {'version': 1, 'protection': PROTECTION, 'purpose': PURPOSE,
                'data': base64.b64encode(protected).decode('ascii')}
    _atomic_write(target, json.dumps(envelope, separators=(',', ':')).encode('utf-8'))
    return {'ok': True, 'credentials_saved': True, 'credential_file': str(target),
            'protection': PROTECTION}


def save_interactive(path=None):
    return save_credentials(prompt_credentials(), path)


def _read_envelope(path):
    try:
        if path.stat().st_size > FILE_LIMIT:
            raise ValueError('oversized')
        envelope = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(envelope, dict) or envelope.get('version') != 1
                or envelope.get('protection') != PROTECTION or envelope.get('purpose') != PURPOSE):
            raise ValueError('invalid envelope')
        encoded = envelope.get('data')
        if not isinstance(encoded, str):
            raise ValueError('invalid data')
        protected = base64.b64decode(encoded, validate=True)
        if not protected:
            raise ValueError('empty data')
        return protected
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ProductError('The protected credential file is missing, damaged, or unreadable.') from None


def load_credentials(path=None):
    target = credential_path(path)
    protected = _read_envelope(target)
    try:
        credentials = json.loads(unprotect_bytes(protected).decode('utf-8'))
        return _validate_credentials(credentials)
    except (ValueError, UnicodeError, RecursionError):
        raise ProductError('Could not unlock valid login credentials from the protected file.') from None


def credential_status(path=None):
    target = credential_path(path)
    saved = target.is_file()
    if saved:
        _read_envelope(target)
    return {'ok': True, 'credentials_saved': saved, 'credential_file': str(target),
            'protection': PROTECTION, 'credentials_verified': False}
