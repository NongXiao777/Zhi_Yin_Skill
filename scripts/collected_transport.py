"""Use an explicitly configured, authorized collected-product transport."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess

from collected_products import collection, decode_json, encode_json, product_number, record_result
from erp_products import FILE_LIMIT, ProductError


TRANSPORT_ENV = 'ZHIYING_COLLECTED_TRANSPORT'
EDIT_FIELDS = {'sale_intro': dict, 'sale_stock': list}


def transport_command(args):
    selected = args.transport or os.environ.get(TRANSPORT_ENV)
    if not selected:
        raise ProductError(f'Live TCP transport is not configured. Set {TRANSPORT_ENV} or pass --transport.')
    executable = Path(selected).expanduser().resolve()
    if not executable.is_file() or executable.suffix.lower() in ('.bat', '.cmd'):
        raise ProductError('Specify an existing transport executable. For a script, pass its interpreter and --transport-arg.')
    return [str(executable), *args.transport_arg]


def request(transport, payload):
    # Credentials belong to the configured transport. Its raw stdout and stderr stay out of CLI output.
    try:
        proc = subprocess.run(transport, input=encode_json(payload).encode('utf-8'), capture_output=True, timeout=30)
        if proc.returncode or len(proc.stdout) > FILE_LIMIT:
            raise ValueError('Transport subprocess failed')
        response = decode_json(proc.stdout.decode('utf-8-sig'))
    except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired):
        raise ProductError(f"{payload['command']} did not return a usable transport response") from None
    if not isinstance(response, dict) or response.get('ok') is not True:
        if isinstance(response, dict) and response.get('error') == 'conflict':
            raise ProductError('Transport reported an update conflict. Read the current product before retrying.')
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
    result = record_result(args, product_id, record, edit=edit)
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
    except ProductError as error:
        raise ProductError(f'{error}. Update outcome is unverified. Read the product before another write.') from None

    try:
        confirmed = detail(transport, product_id)
        matches = all(collection(confirmed, field, EDIT_FIELDS[field])
                      == collection(record, field, EDIT_FIELDS[field]) for field in changed)
    except ProductError:
        raise ProductError('Update acknowledged, but the read-back failed. Read the product before another write.') from None
    if not matches:
        raise ProductError('Update acknowledged, but the read-back differs. Read the product before another write.')
    return {**result, 'update_sent': True, 'transport_calls': 3, 'remote_read_back_verified': True}
