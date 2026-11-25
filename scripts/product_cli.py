"""Fixed native product operations with explicit saved plans and rollback data."""

from pathlib import Path
from contextlib import contextmanager
import os

from product_model import (MutationPlan, ProductDataError, assert_base_unchanged,
                           compact_summary, decode_json, encode_json, fingerprint,
                           parse_snapshot, plan_changes, verify_readback, verify_restore)


def add_commands(commands):
    export = commands.add_parser('session-export', help='Export the running client session to a protected local file')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--pid', type=int)
    export.add_argument('--diagnostics-dir', type=Path, required=True,
                        help='Directory containing the supported ClrMD dependencies')
    detail = commands.add_parser('product-detail', help='Read a product through the native TCP protocol')
    detail.add_argument('--session', type=Path, required=True)
    detail.add_argument('--namespace', choices=('sale', 'spider'), required=True)
    detail.add_argument('--id', type=int, required=True)
    detail.add_argument('--limit', type=int, choices=range(1, 101), default=10)
    detail.add_argument('--output', type=Path, help='Save the complete snapshot locally')
    plan = commands.add_parser('product-plan', help='Read and preview a fixed JSON instruction without writing')
    plan.add_argument('--session', type=Path, required=True)
    plan.add_argument('--instruction', type=Path, required=True)
    plan.add_argument('--output', type=Path, required=True)
    apply = commands.add_parser('product-apply', help='Apply a saved plan once and read it back')
    apply.add_argument('--session', type=Path, required=True)
    apply.add_argument('--plan', type=Path, required=True)
    restore = commands.add_parser('product-restore', help='Restore the original targeted fields from a saved plan')
    restore.add_argument('--session', type=Path, required=True)
    restore.add_argument('--plan', type=Path, required=True)


def _read_document(path):
    value = decode_json(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ProductDataError('The local input must be a JSON object')
    return value


def _write_document(path, value):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(encode_json(value), encoding='utf-8')
    temporary.replace(path)


@contextmanager
def _plan_lock(path):
    resolved = path.resolve()
    lock_path = resolved.with_name(resolved.name + '.lock')
    with lock_path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            if lock_path.stat().st_size == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ProductDataError('Another process is using this plan') from error
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ProductDataError('Another process is using this plan') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _client(path):
    from zying_session import load_session
    from zying_transport import NativeClient
    config = load_session(path)
    return NativeClient(config)


def _read_snapshot(client, product_id, namespace):
    return parse_snapshot(client.read_detail(namespace, product_id), product_id, namespace)


def create_plan(client, instruction, path):
    if path.exists():
        raise ProductDataError('Plan file already exists; choose a new path')
    if instruction.get('operation') != 'update_product':
        raise ProductDataError('Instruction operation must be update_product')
    allowed = {'operation', 'namespace', 'product_id', 'variant_key', 'new_money',
               'description_language', 'append_character'}
    unknown = set(instruction) - allowed
    if unknown:
        raise ProductDataError('Unknown instruction fields: ' + ', '.join(sorted(unknown)))
    if 'product_id' not in instruction or 'namespace' not in instruction:
        raise ProductDataError('Instruction requires product_id and namespace')
    snapshot = _read_snapshot(client, instruction['product_id'], instruction['namespace'])
    plan = plan_changes(snapshot, instruction.get('variant_key'), instruction.get('new_money'),
                        instruction.get('description_language'), instruction.get('append_character'))
    document = {'format': 1, 'state': 'prepared', 'product_id': plan.product_id,
                'namespace': plan.namespace, 'original_record': snapshot.record,
                'updates': plan.updates, 'restore_updates': plan.restore_updates,
                'base_fingerprint': plan.base_fingerprint, 'expected_record': plan.expected_record,
                'changes': plan.changes}
    _write_document(path, document)
    result = plan.preview()
    result.update({'ok': True, 'plan': str(path.resolve()), 'state': 'prepared',
                   'titles': snapshot.titles, 'business_requests_sent': 1})
    return result


def _load_plan(path):
    document = _read_document(path)
    if document.get('format') != 1:
        raise ProductDataError('Unsupported plan format')
    needed = ('state', 'product_id', 'namespace', 'original_record', 'updates',
              'restore_updates', 'base_fingerprint', 'expected_record', 'changes')
    if any(field not in document for field in needed):
        raise ProductDataError('Plan file is incomplete')
    original = parse_snapshot({'root': [document['original_record']]},
                              document['product_id'], document['namespace'])
    plan = MutationPlan(document['product_id'], document['namespace'], document['updates'],
                        document['restore_updates'], document['base_fingerprint'],
                        document['expected_record'], document['changes'])
    assert_base_unchanged(original, plan)
    # Local plans are a boundary: allow only the operations this CLI creates.
    fields = set(plan.updates)
    if not fields <= {'id', 'sale_stock', 'sale_intro'} or fields == {'id'}:
        raise ProductDataError('Plan contains unsupported update fields')
    if set(plan.restore_updates) != fields:
        raise ProductDataError('Plan update and restore fields differ')
    if plan.updates.get('id') != plan.product_id or plan.restore_updates.get('id') != plan.product_id:
        raise ProductDataError('Plan targets a different product id')
    for field in fields - {'id'}:
        if plan.restore_updates[field] != original.record[field]:
            raise ProductDataError('Plan rollback values differ from the original snapshot')
        if plan.expected_record.get(field) != plan.updates[field]:
            raise ProductDataError('Plan expected values differ from its updates')
    for field in set(original.record) | set(plan.expected_record):
        if field not in fields and original.record.get(field) != plan.expected_record.get(field):
            raise ProductDataError('Plan changes a field outside its update set')
    return document, original, plan


def apply_plan(client, path):
    with _plan_lock(path):
        return _apply_plan(client, path)


def _apply_plan(client, path):
    document, original, plan = _load_plan(path)
    if document['state'] != 'prepared':
        raise ProductDataError('Plan was already submitted; inspect or restore it instead of replaying')
    current = _read_snapshot(client, plan.product_id, plan.namespace)
    assert_base_unchanged(current, plan)
    # Persist intent before network I/O, so a timeout cannot silently enable replay.
    document['state'] = 'write_attempted'
    _write_document(path, document)
    client.update_fields(plan.namespace, plan.product_id,
                         {name: value for name, value in plan.updates.items() if name != 'id'})
    after = _read_snapshot(client, plan.product_id, plan.namespace)
    verification = verify_readback(original, after, plan)
    document.update({'state': 'applied' if verification['verified'] else 'verification_failed',
                     'readback_record': after.record, 'verification': verification})
    _write_document(path, document)
    return {'ok': verification['verified'], 'state': document['state'],
            'product_id': plan.product_id, 'changes': plan.changes,
            'verification': verification, 'business_requests_sent': 3}


def restore_plan(client, path):
    with _plan_lock(path):
        return _restore_plan(client, path)


def _restore_plan(client, path):
    document, original, plan = _load_plan(path)
    if document['state'] not in ('write_attempted', 'applied', 'verification_failed', 'restore_attempted'):
        raise ProductDataError('Plan does not contain an outstanding write to restore')
    current = _read_snapshot(client, plan.product_id, plan.namespace)
    already = verify_restore(original, current)
    if already['restored']:
        document['state'] = 'restored'
        _write_document(path, document)
        return {'ok': True, 'state': 'restored', 'verification': already,
                'business_requests_sent': 1}
    # Recover a write with unknown outcome only when the targeted fields still
    # equal this plan; never replace another user's intervening field changes.
    expected = parse_snapshot({'root': [plan.expected_record]}, plan.product_id, plan.namespace)
    observed = parse_snapshot({'root': [current.record]}, plan.product_id, plan.namespace)
    for field in plan.updates:
        if field == 'id':
            continue
        left = observed.record[field]
        right = expected.record[field]
        if field == 'sale_stock':
            left, right = observed.variants, expected.variants
        elif field == 'sale_intro':
            left, right = observed.descriptions, expected.descriptions
        if left != right:
            raise ProductDataError('Target field changed after this plan; automatic restoration stopped: ' + field)
    document['state'] = 'restore_attempted'
    _write_document(path, document)
    client.update_fields(plan.namespace, plan.product_id,
                         {name: value for name, value in plan.restore_updates.items() if name != 'id'})
    restored = _read_snapshot(client, plan.product_id, plan.namespace)
    verification = verify_restore(original, restored)
    document.update({'state': 'restored' if verification['restored'] else 'restore_verification_failed',
                     'restore_verification': verification, 'restored_record': restored.record})
    _write_document(path, document)
    return {'ok': verification['restored'], 'state': document['state'],
            'product_id': plan.product_id, 'verification': verification, 'business_requests_sent': 3}


def run(args):
    if args.action == 'session-export':
        from zying_session import export_session
        return export_session(args.app, args.output, args.pid, deps_dir=args.diagnostics_dir)
    client = _client(args.session)
    if args.action == 'product-detail':
        snapshot = _read_snapshot(client, args.id, args.namespace)
        if args.output:
            _write_document(args.output, {'root': [snapshot.record]})
        return {'ok': True, **compact_summary(snapshot, args.limit), 'business_requests_sent': 1}
    if args.action == 'product-plan':
        return create_plan(client, _read_document(args.instruction), args.output)
    if args.action == 'product-apply':
        return apply_plan(client, args.plan)
    return restore_plan(client, args.plan)
