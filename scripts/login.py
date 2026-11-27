"""Perform terminal login and store only a protected native TCP session."""
import argparse
import base64
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

from erp_products import ProductError
from collected_transport import native_command, request, SESSION_ENV
from client_version import DLL_KEYS, fingerprint
import login_credentials as credentials


LOGIN_COMMANDS = ('credentials-save', 'credentials-status', 'login', 'login-probe', 'login-status', 'login-native')
SESSION_PURPOSE = 'zhiying-login-session'
SESSION_DLLS = ('ZYing.Work.dll', 'ZYing.User.dll')
SESSION_FILE_LIMIT = 1_000_000


def session_path(path=None):
    selected = path or os.environ.get(SESSION_ENV)
    if selected:
        return Path(selected).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise ProductError('Set LOCALAPPDATA or ZHIYING_SESSION_FILE for local session storage.')
    return Path(local).resolve() / 'ZhiYingSkill' / 'session.dpapi'


def _validated_session(session):
    try:
        if not isinstance(session, dict):
            raise ValueError()
        address = str(ipaddress.ip_address(session['server_address']))
        port = session['server_port']
        token = uuid.UUID(session['token'])
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536 or token.int == 0:
            raise ValueError()
        result = {'server_address': address, 'server_port': port, 'token': str(token)}
        if 'exchange_state' in session:
            state = session['exchange_state']
            if not isinstance(state, int) or isinstance(state, bool) or not -2147483648 <= state <= 2147483647:
                raise ValueError()
            result['exchange_state'] = state
        if 'device_id' in session:
            device = uuid.UUID(session['device_id'])
            if device.int == 0:
                raise ValueError()
            result['device_id'] = str(device)
        if 'user_id' in session:
            user_id = session['user_id']
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                raise ValueError()
            result['user_id'] = user_id
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProductError('Login did not return a valid authenticated TCP session.') from None


def _client_hashes(value):
    if not isinstance(value, dict):
        raise ValueError('Expected client fingerprints')
    for dll in SESSION_DLLS:
        hash_value = value.get(DLL_KEYS[dll])
        if not isinstance(hash_value, str) or not re.fullmatch('[0-9A-F]{64}', hash_value):
            raise ValueError('Invalid client fingerprint')
    return {DLL_KEYS[dll]: value[DLL_KEYS[dll]] for dll in SESSION_DLLS}


def save_session(session, path=None, client_hashes=None):
    session = _validated_session(session)
    target = session_path(path)
    plaintext = json.dumps(session, separators=(',', ':')).encode('utf-8')
    protected = credentials.protect_bytes(plaintext)
    envelope = {'version': 1, 'protection': credentials.PROTECTION, 'purpose': SESSION_PURPOSE,
                'data': base64.b64encode(protected).decode('ascii')}
    if client_hashes is not None:
        try:
            envelope['client_hashes'] = _client_hashes(client_hashes)
        except ValueError:
            raise ProductError('Login returned invalid client fingerprints.') from None
    credentials._atomic_write(target, json.dumps(envelope, separators=(',', ':')).encode('utf-8'))
    return target


def _read_session_file(path):
    with path.open('rb') as stream:
        raw = stream.read(SESSION_FILE_LIMIT + 1)
    if len(raw) > SESSION_FILE_LIMIT:
        raise ValueError('Session file exceeds the size limit')
    envelope = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(envelope, dict):
        raise ValueError('Invalid session file')
    return raw, envelope


def _protected_client_hashes(envelope):
    if (envelope.get('version') != 1 or envelope.get('protection') != credentials.PROTECTION or
            envelope.get('purpose') != SESSION_PURPOSE or not envelope.get('data') or
            not isinstance(envelope['data'], str)):
        raise ValueError('Invalid protected session')
    return _client_hashes(envelope.get('client_hashes'))


def login_status(path=None, app=None):
    target = session_path(path)
    saved = target.is_file()
    result = {'ok': True, 'session_saved': saved, 'session_file': str(target),
              'session_verified': False}
    if app is None:
        return result
    if not saved:
        return {**result, 'client_binding': 'missing', 'relogin_recommended': True}
    try:
        _, envelope = _read_session_file(target)
        if 'client_hashes' not in envelope:
            return {**result, 'client_binding': 'untracked', 'relogin_recommended': True}
        expected = _protected_client_hashes(envelope)
    except (OSError, ValueError):
        return {**result, 'client_binding': 'invalid_session', 'relogin_recommended': True}

    dlls = {}
    for dll in SESSION_DLLS:
        try:
            dlls[dll] = 'matched' if fingerprint(app.parent / dll) == expected[DLL_KEYS[dll]] else 'changed'
        except OSError:
            dlls[dll] = 'unavailable'
    status = 'matched'
    if 'changed' in dlls.values():
        status = 'changed'
    elif 'unavailable' in dlls.values():
        status = 'unavailable'
    return {**result, 'client_binding': status, 'relogin_recommended': status != 'matched', 'client_dlls': dlls}


def _endpoint_override(args):
    address = getattr(args, 'server_address', None)
    port = getattr(args, 'server_port', None)
    if address is None and port is None:
        return {}
    try:
        if address is None or port is None or not 0 < port < 65536:
            raise ValueError()
        return {'server_address': str(ipaddress.ip_address(address)), 'server_port': port}
    except (ValueError, TypeError):
        raise ProductError('Supply both a valid server IP address and TCP port when overriding the client endpoint.') from None


def _native_login(args):
    target = session_path(args.session_file)
    if getattr(args, 'if_needed', False):
        status = login_status(target, args.app)
        if status['client_binding'] == 'matched':
            return {**status, 'login_attempted': False}
    command = native_command(args.app, source_file='NativeLoginHost.cs')
    with TemporaryDirectory(prefix='zhiying-login-') as directory:
        pending = Path(directory) / 'session.dpapi'
        try:
            completed = subprocess.run([*command, str(pending), str(args.timeout)],
                                       capture_output=True, timeout=args.timeout + 30)
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        # The host creates this attempt-specific file only after authenticated login.
        # Vendor window shutdown can interrupt the final stdout message.
        if pending.is_file():
            try:
                raw, envelope = _read_session_file(pending)
                _protected_client_hashes(envelope)
                credentials._atomic_write(target, raw)
            except (OSError, ValueError, ProductError):
                raise ProductError('Native login succeeded, but protected session storage failed.') from None
            return {'ok': True, 'authenticated': True, 'login_attempted': True, 'session_saved': True,
                    'session_file': str(target), 'protection': credentials.PROTECTION, 'login_mode': 'native_window'}

        code = None
        if completed is not None:
            try:
                response = json.loads(completed.stdout.decode('utf-8-sig'))
                if isinstance(response, dict) and isinstance(response.get('error'), str):
                    code = response['error']
            except ValueError:
                pass
        errors = {
            'unsupported_client_version': 'The client update needs a verified native login profile. '
                                          'Run client-diagnose --symbols using the same --app path.',
            'native_login_cancelled_or_timed_out': 'Native login was cancelled or timed out',
            'native_session_save_failed': 'Native login succeeded, but protected session storage failed',
        }
        raise ProductError(errors.get(code, 'Could not open or complete the native login window'))


def login_result(args):
    if args.action == 'credentials-save':
        return credentials.save_interactive(args.credential_file)
    if args.action == 'credentials-status':
        return credentials.credential_status(args.credential_file)
    if args.action == 'login-status':
        return login_status(args.session_file, args.app)
    if args.action == 'login-native':
        return _native_login(args)
    if args.action == 'login-probe':
        response = request(native_command(args.app), {'command': 'login.probe'})
        return {key: response[key] for key in (
            'ok', 'native_components_loaded', 'login_command', 'password_was_encoded',
            'login_endpoint_resolved', 'authenticated', 'network_requests_sent',
            'parameter_bytes', 'request_bytes') if key in response}

    endpoint = _endpoint_override(args)
    transport = native_command(args.app)
    entered = (credentials.load_credentials(args.credential_file) if args.saved
               else credentials.prompt_credentials())
    try:
        # Secrets travel over this private stdin pipe, never in executable arguments.
        response = request(transport, {'command': 'common.login', **entered, **endpoint})
        if response.get('authenticated') is not True:
            raise ProductError('The server did not confirm an authenticated login.')
        session = _validated_session(response.get('session'))
        target = save_session(session, args.session_file, response.get('client_hashes'))
        result = {'ok': True, 'authenticated': True, 'session_saved': True,
                  'session_file': str(target), 'protection': credentials.PROTECTION}
        if args.remember:
            try:
                credentials.save_credentials(entered, args.credential_file)
                result['credentials_saved'] = True
            except ProductError:
                # Login is already successful; do not misreport it as a failed login.
                result.update(credentials_saved=False, credential_save_failed=True)
        return result
    finally:
        entered.clear()


def add_login_commands(commands):
    store = argparse.ArgumentParser(add_help=False)
    store.add_argument('--credential-file', type=Path, help='protected local credential file')
    commands.add_parser('credentials-save', parents=[store], help='enter phone and hidden password; save locally without logging in')
    commands.add_parser('credentials-status', parents=[store], help='check protected credential presence without unlocking it')
    status = commands.add_parser('login-status', help='check the saved session and its client DLL fingerprints offline')
    status.add_argument('--session-file', type=Path)
    commands.add_parser('login-probe', help='encode a synthetic login request without network or credentials')
    native = commands.add_parser('login-native', help='open the vendor login window; user types password and session is protected after success')
    native.add_argument('--session-file', type=Path)
    native.add_argument('--if-needed', action='store_true', help='skip the window if a saved session matches the current Work and User DLLs')
    native.add_argument('--timeout', type=int, choices=range(10, 1801), metavar='SECONDS', default=300)
    sign_in = commands.add_parser('login', parents=[store], help='login once using terminal input or locally saved credentials')
    sign_in.add_argument('--saved', action='store_true', help='unlock previously saved credentials instead of prompting')
    sign_in.add_argument('--remember', action='store_true', help='save credentials after successful login')
    sign_in.add_argument('--session-file', type=Path, help='protected session destination')
    sign_in.add_argument('--server-address', help='explicit login server IP override')
    sign_in.add_argument('--server-port', type=int, help='explicit login server TCP port override')
