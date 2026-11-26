"""Perform terminal login and store only a protected native TCP session."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import uuid

from erp_products import ProductError
from collected_transport import native_command, request, SESSION_ENV
import login_credentials as credentials


LOGIN_COMMANDS = ('credentials-save', 'credentials-status', 'login', 'login-probe', 'login-status')
SESSION_PURPOSE = 'zhiying-login-session'


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


def save_session(session, path=None):
    session = _validated_session(session)
    target = session_path(path)
    plaintext = json.dumps(session, separators=(',', ':')).encode('utf-8')
    protected = credentials.protect_bytes(plaintext)
    envelope = {'version': 1, 'protection': credentials.PROTECTION, 'purpose': SESSION_PURPOSE,
                'data': base64.b64encode(protected).decode('ascii')}
    credentials._atomic_write(target, json.dumps(envelope, separators=(',', ':')).encode('utf-8'))
    return target


def login_status(path=None):
    target = session_path(path)
    saved = target.is_file()
    return {'ok': True, 'session_saved': saved, 'session_file': str(target),
            'session_verified': False}


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


def login_result(args):
    if args.action == 'credentials-save':
        return credentials.save_interactive(args.credential_file)
    if args.action == 'credentials-status':
        return credentials.credential_status(args.credential_file)
    if args.action == 'login-status':
        return login_status(args.session_file)
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
        target = save_session(session, args.session_file)
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
    status = commands.add_parser('login-status', help='check saved session presence; does not contact the server')
    status.add_argument('--session-file', type=Path)
    commands.add_parser('login-probe', help='encode a synthetic login request without network or credentials')
    sign_in = commands.add_parser('login', parents=[store], help='login once using terminal input or locally saved credentials')
    sign_in.add_argument('--saved', action='store_true', help='unlock previously saved credentials instead of prompting')
    sign_in.add_argument('--remember', action='store_true', help='save credentials after successful login')
    sign_in.add_argument('--session-file', type=Path, help='protected session destination')
    sign_in.add_argument('--server-address', help='explicit login server IP override')
    sign_in.add_argument('--server-port', type=int, help='explicit login server TCP port override')
