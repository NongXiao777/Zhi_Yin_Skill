"""Use an explicitly configured, authorized collected-product transport."""
from copy import deepcopy
from pathlib import Path
import os
import shutil
import subprocess

from collected_products import NATIVE_COPY_FIELDS, collection, decode_json, encode_json, product_number, record_result
from erp_products import FILE_LIMIT, ProductError


TRANSPORT_ENV = 'ZHIYING_COLLECTED_TRANSPORT'
SESSION_ENV = 'ZHIYING_SESSION_FILE'
EDIT_FIELDS = {'sale_intro': dict, 'sale_stock': list, 'listing_copy': dict}
EDIT_FIELDS.update({field: dict for field in NATIVE_COPY_FIELDS.values()})


class TransportConflict(ProductError):
    pass


def native_command(app):
    shell = shutil.which('pwsh')
    if shell is None:
        raise ProductError('The native transport needs PowerShell 7 and the installed .NET 6 Desktop Runtime')
    build = Path(__file__).parent / 'native' / 'Build.ps1'
    try:
        completed = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(build),
                                    '-AppDirectory', str(app.parent)], capture_output=True, timeout=30)
        result = decode_json(completed.stdout.decode('utf-8-sig'))
        if completed.returncode or result.get('ok') is not True:
            raise ValueError('Build failed')
        return [result['executable'], result['assembly'], result['app_directory'], str(build.with_name('client-profiles.json'))]
    except (OSError, ValueError, KeyError, AttributeError, subprocess.TimeoutExpired):
        raise ProductError('Could not build the native transport. Verify PowerShell 7 and .NET 6 Desktop Runtime.') from None


def native_probe(app):
    response = request(native_command(app), {'command': 'native.probe'})
    return {**response, 'mode': 'native_component_probe', 'real_product_verified': False}


def transport_command(args):
    selected = args.transport or os.environ.get(TRANSPORT_ENV)
    if not selected:
        local = os.environ.get('LOCALAPPDATA')
        default_session = Path(local) / 'ZhiYingSkill' / 'session.dpapi' if local else None
        if os.environ.get(SESSION_ENV) or default_session and default_session.is_file():
            return native_command(args.app)
        raise ProductError(f'Live TCP transport is not configured. Set {SESSION_ENV} for the native transport, '
                           f'or {TRANSPORT_ENV} or --transport for another authorized transport.')
    executable = Path(selected).expanduser().resolve()
    if not executable.is_file() or executable.suffix.lower() in ('.bat', '.cmd'):
        raise ProductError('Specify an existing transport executable. For a script, pass its interpreter and --transport-arg.')
    return [str(executable), *args.transport_arg]


def request(transport, payload):
    # Credentials belong to the configured transport. Its raw stdout and stderr stay out of CLI output.
    try:
        proc = subprocess.run(transport, input=encode_json(payload).encode('utf-8'), capture_output=True, timeout=30)
        if len(proc.stdout) > FILE_LIMIT:
            raise ValueError('Transport subprocess failed')
        response = decode_json(proc.stdout.decode('utf-8-sig'))
        if proc.returncode and (not isinstance(response, dict) or response.get('ok') is not False):
            raise ValueError('Transport subprocess failed')
    except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired):
        raise ProductError(f"{payload['command']} did not return a usable transport response") from None
    if not isinstance(response, dict) or response.get('ok') is not True:
        if isinstance(response, dict) and response.get('error') == 'conflict':
            raise TransportConflict('Transport reported an update conflict. Read the current product before retrying.')
        native_errors = {
            'missing_session_file': 'The native transport needs a local session file in ZHIYING_SESSION_FILE',
            'unsupported_client_version': 'The installed client differs from the verified native transport version',
            'invalid_session_configuration': 'The local session needs the actual server address, port and login token',
            'server_rejected_request': 'The server rejected the native request. Verify the login session and account permissions',
            'login_rejected': 'Login was rejected. Check the phone number, password and account state before trying again',
            'login_requires_additional_verification': 'Login requires additional account verification; this CLI did not bypass it',
            'login_requires_password_change': 'The account requires a password change before command-line login can continue',
            'password_change_required': 'The account requires a password change before command-line login can continue',
            'login_response_missing_session': 'The login response did not contain a usable authenticated session',
            'login_response_incomplete': 'The login response did not contain a usable authenticated session',
            'invalid_login_credentials': 'Enter a valid phone number and nonempty password in the terminal',
            'invalid_login_input': 'Enter a valid phone number and nonempty password in the terminal',
            'additional_verification_required': 'Login requires additional account verification; this CLI did not bypass it',
            'password_encoding_failed': 'The native client could not encode the password; no login request was sent',
            'private_login_pipe_required': 'Login credentials must be supplied through the CLI private subprocess pipe',
            'login_endpoint_unavailable': 'The installed client login endpoint could not be resolved',
            'invalid_protected_session': 'The saved session could not be unlocked by this Windows user',
            'tcp_timeout': 'The TCP server did not respond before the timeout',
        }
        if isinstance(response, dict) and response.get('error') == 'server_rejected_request':
            reason = response.get('reason')
            result = response.get('server_result')
            reasons = {'session_rejected': 'The server rejected the session',
                       'permission_denied': 'The server denied account permissions',
                       'command_rejected': 'The server rejected the command',
                       'record_not_found': 'The server could not find the requested record',
                       'invalid_parameters': 'The server rejected the parameters'}
            diagnostic = f' (server_result={result})' if isinstance(result, int) and not isinstance(result, bool) else ''
            raise ProductError(reasons.get(reason, native_errors['server_rejected_request']) + diagnostic)
        if isinstance(response, dict) and response.get('error') == 'login_rejected':
            reasons = {
                'credentials_rejected': 'The login service rejected the supplied account/password',
                'account_not_found': 'The login service could not find the account',
                'client_update_required': 'The login service requires a newer client',
                'additional_verification_required': 'The login service requires additional verification',
                'account_unavailable': 'The login service reports the account is unavailable',
            }
            reason = response.get('reason')
            result = response.get('server_result')
            diagnostic = f' (server_result={result})' if isinstance(result, int) and not isinstance(result, bool) else ''
            raise ProductError(reasons.get(reason, native_errors['login_rejected']) + diagnostic)
        if isinstance(response, dict) and response.get('error') in native_errors:
            raise ProductError(native_errors[response['error']])
        raise ProductError(f"{payload['command']} was not acknowledged by the transport")
    return response


def detail(transport, product_id):
    response = request(transport, {'command': 'spider.detail', 'id': product_id})
    record = response.get('record')
    if not isinstance(record, dict) or 'sale_id' not in record or product_number(record['sale_id']) != product_id:
        raise ProductError('Transport detail returned the wrong product or omitted its sale_id')
    return record


def live_result(args, *, edit=False):
    transport = transport_command(args)
    product_id = product_number(args.product_id)
    record = detail(transport, product_id)
    before = {field: deepcopy(record.get(field)) for field in EDIT_FIELDS} if edit else {}
    result = record_result(args, product_id, record, edit=edit, live=True)
    result.update(mode='live_transport', transport_calls=1)
    if not edit:
        return result

    changed = {field: record[field] for field, old in before.items() if record.get(field) != old}
    if not changed:
        return {**result, 'update_sent': False}

    try:
        request(transport, {
            'command': 'spider.update', 'id': product_id, 'fields': changed,
            'expected': {field: before[field] for field in changed},
        })
    except TransportConflict:
        raise
    except ProductError as error:
        message = str(error).rstrip('.')
        raise ProductError(f'{message}. Update outcome is unverified. Read the product before another write.') from None

    try:
        confirmed = detail(transport, product_id)
        matches = all(collection(confirmed, field, EDIT_FIELDS[field])
                      == collection(record, field, EDIT_FIELDS[field]) for field in changed)
    except ProductError:
        raise ProductError('Update acknowledged, but the read-back failed. Read the product before another write.') from None
    if not matches:
        raise ProductError('Update acknowledged, but the read-back differs. Read the product before another write.')
    return {**result, 'update_sent': True, 'transport_calls': 3, 'remote_read_back_verified': True}
