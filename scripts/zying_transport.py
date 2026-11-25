"""ZYing native record codec and TCP framing derived from client IL.

Credentials and the selected endpoint must come from a legitimate local session.
This module performs one request without replaying writes or guessing login data.
"""

from dataclasses import dataclass
from decimal import Decimal
import gzip
import io
import socket
import struct
import uuid


class ProtocolError(ValueError):
    pass


class ServerError(RuntimeError):
    def __init__(self, result):
        super().__init__('The server rejected the operation (result=%s)' % result)
        self.result = result


@dataclass
class Record:
    name: str
    columns: list
    rows: list
    page: int = 0
    page_size: int = 0
    max_count: int = 0


@dataclass
class Response:
    protocol_version: int
    result: int
    is_error: bool
    message: str
    properties: dict
    records: dict


@dataclass(repr=False)
class Session:
    host: str
    port: int
    client_id: uuid.UUID
    token: uuid.UUID
    protocol_version: int
    app_revision: int
    timeout: float = 15
    mode: object = 'M'


class Reader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def take(self, size):
        if size < 0:
            raise ProtocolError('Negative payload length')
        data = self.stream.read(size)
        if len(data) != size:
            raise ProtocolError('Truncated protocol payload')
        return data

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def name(self):
        return self.take(self.number('B')).decode('utf-8')

    def text(self):
        return self.take(self.number('i')).decode('utf-8')

    def remaining(self):
        return self.stream.getbuffer().nbytes - self.stream.tell()


def encode_name(value):
    data = value.encode('utf-8')
    if len(data) > 255:
        raise ProtocolError('Protocol name exceeds one-byte length')
    return bytes([len(data)]) + data


def encode_text(value):
    data = value.encode('utf-8')
    return struct.pack('<i', len(data)) + data


def encode_parameters(parameters):
    return b''.join(encode_name(name) + encode_text(str(value))
                    for name, value in parameters.items())


def decimal_bytes(value):
    value = Decimal(value)
    if not value.is_finite():
        raise ProtocolError('Decimal must be finite')
    sign, digits, exponent = value.as_tuple()
    integer = int(''.join(str(digit) for digit in digits))
    scale = -exponent
    if exponent > 0:
        integer *= 10 ** exponent
        scale = 0
    if scale > 28 or integer.bit_length() > 96:
        raise ProtocolError('Value does not fit System.Decimal')
    return struct.pack('<IIII', integer & 0xffffffff,
                       (integer >> 32) & 0xffffffff, integer >> 64,
                       (scale << 16) | (sign << 31))


def read_decimal(reader):
    low, middle, high, flags = struct.unpack('<IIII', reader.take(16))
    scale = (flags >> 16) & 0xff
    if flags & 0x7f00ffff or scale > 28:
        raise ProtocolError('Invalid System.Decimal flags')
    coefficient = low | (middle << 32) | (high << 64)
    sign = 1 if flags & 0x80000000 else 0
    return Decimal((sign, tuple(int(c) for c in str(coefficient)), -scale))


SCALAR_FORMATS = {3: '?', 4: 'H', 5: 'b', 6: 'B', 7: 'h', 8: 'H',
                  9: 'i', 10: 'I', 11: 'q', 12: 'Q', 13: 'f', 14: 'd', 16: 'q'}


def encode_value(type_code, value):
    if type_code == 18:
        return encode_text(value)
    if type_code == 15:
        return decimal_bytes(value)
    if type_code in SCALAR_FORMATS:
        return struct.pack('<' + SCALAR_FORMATS[type_code], value)
    if type_code == 0:
        return uuid.UUID(str(value)).bytes_le
    if type_code in (106, 109, 111, 115):
        base = type_code - 100
        if type_code != 106 and len(value) > 65535:
            raise ProtocolError('Numeric array exceeds two-byte count')
        count_format = '<i' if type_code == 106 else '<H'
        return struct.pack(count_format, len(value)) + b''.join(encode_value(base, x) for x in value)
    if type_code == 118:
        if len(value) > 10000:
            raise ProtocolError('String array exceeds vendor count limit')
        parts = [struct.pack('<H', len(value))]
        for text in value:
            data = text.encode('utf-8')
            if len(data) > 65535:
                raise ProtocolError('String array item exceeds vendor length limit')
            parts.extend((struct.pack('<H', len(data)), data))
        return b''.join(parts)
    raise ProtocolError('Unsupported record type code: %s' % type_code)


def read_value(reader, type_code):
    if type_code == 18:
        return reader.text()
    if type_code == 15:
        return read_decimal(reader)
    if type_code in SCALAR_FORMATS:
        return reader.number(SCALAR_FORMATS[type_code])
    if type_code == 0:
        return str(uuid.UUID(bytes_le=reader.take(16)))
    if type_code in (106, 109, 111, 115):
        count = reader.number('i' if type_code == 106 else 'H')
        if count < 0:
            raise ProtocolError('Negative array count')
        return [read_value(reader, type_code - 100) for _ in range(count)]
    if type_code == 118:
        count = reader.number('H')
        if count > 10000:
            raise ProtocolError('String array exceeds vendor count limit')
        return [reader.take(reader.number('H')).decode('utf-8')
                for _ in range(count)]
    raise ProtocolError('Unsupported record type code: %s' % type_code)


def encode_records(records):
    if len(records) > 255:
        raise ProtocolError('Record count exceeds one-byte length')
    parts = [bytes([len(records)])]
    names = set()
    for record in records:
        name = record.name or 'root'
        if name in names:
            raise ProtocolError('Duplicate record name')
        names.add(name)
        if len(record.columns) > 255:
            raise ProtocolError('Column count exceeds one-byte length')
        parts.append(struct.pack('<Biiii', len(record.columns), len(record.rows),
                                 record.page, record.page_size, record.max_count))
        parts.append(encode_name(name))
        column_names = [column[0] for column in record.columns]
        if len(set(column_names)) != len(column_names):
            raise ProtocolError('Duplicate column name')
        for column, type_code in record.columns:
            parts.extend((encode_name(column), bytes([type_code])))
        for row in record.rows:
            if set(row) != set(column_names):
                raise ProtocolError('Row values do not match the declared columns')
            parts.extend(encode_value(type_code, row[column])
                         for column, type_code in record.columns)
    return b''.join(parts)


def read_records(reader):
    records = {}
    for _ in range(reader.number('B')):
        column_count = reader.number('B')
        row_count, page, page_size, max_count = [reader.number('i') for _ in range(4)]
        if row_count < 0:
            raise ProtocolError('Negative record row count')
        name = reader.name() or 'root'
        columns = [(reader.name(), reader.number('B')) for _ in range(column_count)]
        if name in records or len({c[0] for c in columns}) != len(columns):
            raise ProtocolError('Duplicate record or column name')
        rows = [{column: read_value(reader, type_code) for column, type_code in columns}
                for _ in range(row_count)]
        records[name] = Record(name, columns, rows, page, page_size, max_count)
    return records


def build_packet(session, command, payload):
    if session.mode not in ('M', 77):
        raise ProtocolError('Unsupported transport mode; only verified M-mode TCP is implemented')
    if not isinstance(payload, bytes):
        raise TypeError('Payload must be encoded bytes')
    body = (struct.pack('<ii', session.protocol_version, session.app_revision)
            + session.client_id.bytes_le + session.token.bytes_le
            + encode_name(command) + payload)
    return b'M' + struct.pack('<i', len(body)) + body


def decompress_response(body):
    # Client Ma39 preserves the first 36 bytes and decodes the ZG/ZB wrapper.
    if len(body) < 38 or body[36] != ord('Z'):
        return body
    if body[37] == ord('G'):
        decoded = gzip.decompress(body[38:])
    elif body[37] == ord('B'):
        try:
            import brotli
        except ImportError as error:
            raise ProtocolError('Brotli response requires the brotli Python package') from error
        decoded = brotli.decompress(body[38:])
    else:
        raise ProtocolError('Unsupported response compression marker')
    return body[:36] + decoded


def decode_response(body, session, property_count=0):
    reader = Reader(decompress_response(body))
    version = reader.number('i')
    client_id = uuid.UUID(bytes_le=reader.take(16))
    token = uuid.UUID(bytes_le=reader.take(16))
    if client_id != session.client_id or token != session.token:
        raise ProtocolError('Response does not match the supplied session identifiers')
    result = reader.number('q')
    is_error = bool(reader.number('B'))
    message = reader.text()
    properties = {}
    for _ in range(property_count):
        name = reader.name()
        properties[name] = reader.text()
    # Ma30 leaves the RecordSet empty when the server response ends after its
    # status message/metadata, as with a login rejection. There is no count byte.
    records = read_records(reader) if reader.remaining() else {}
    if reader.remaining():
        raise ProtocolError('Unexpected bytes after response records')
    return Response(version, result, is_error, message, properties, records)


def receive_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        chunk = connection.recv(count - len(data))
        if not chunk:
            raise ProtocolError('Connection closed before the response was complete')
        data.extend(chunk)
    return bytes(data)


def request(session, command, payload):
    packet = build_packet(session, command, payload)
    with socket.create_connection((session.host, session.port), timeout=session.timeout) as connection:
        connection.sendall(packet)
        marker = receive_exact(connection, 1)
        # In M mode, Reading verifies 'c', reads the metadata count, then the
        # Int32 payload length. Other progress frames do not contain a RecordSet.
        if marker != b'c':
            raise ProtocolError('Unsupported M-mode response frame')
        property_count = receive_exact(connection, 1)[0]
        length = struct.unpack('<i', receive_exact(connection, 4))[0]
        if length < 49:
            raise ProtocolError('Invalid response length')
        body = receive_exact(connection, length)
    response = decode_response(body, session, property_count)
    session.protocol_version = response.protocol_version
    return response


class NativeClient:
    def __init__(self, config):
        if isinstance(config, Session):
            self.session = config
        else:
            self.session = Session(
                host=config['host'], port=int(config['port']),
                client_id=uuid.UUID(str(config['client_id'])),
                token=uuid.UUID(str(config['session_token'])),
                protocol_version=int(config['protocol_version']),
                app_revision=int(config['app_revision']),
                timeout=float(config.get('timeout', 15)), mode=config['mode'])
        if self.session.mode not in ('M', 77):
            raise ProtocolError('Unsupported transport mode; only verified M-mode TCP is implemented')

    def _command(self, namespace, operation):
        if namespace not in ('sale', 'spider'):
            raise ProtocolError('The product namespace must be sale or spider')
        return namespace + '.' + operation

    def read_detail(self, namespace, product_id):
        if not isinstance(product_id, int) or isinstance(product_id, bool) or not 0 < product_id < 2**31:
            raise ProtocolError('Product ID must be a positive Int32')
        response = request(self.session, self._command(namespace, 'detail'),
                           encode_parameters({'id': product_id}))
        if response.is_error:
            raise ServerError(response.result)
        return {name: record.rows for name, record in response.records.items()}

    def update_fields(self, namespace, product_id, fields):
        if not isinstance(product_id, int) or isinstance(product_id, bool) or not 0 < product_id < 2**31:
            raise ProtocolError('Product ID must be a positive Int32')
        column_types = {'sale_stock': 18, 'sale_intro': 18, 'sale_title': 18,
                        'sale_size': 18, 'sale_cur': 18, 'sale_weight': 9,
                        'sale_cost': 15, 'sale_price': 15}
        if not fields or any(name not in column_types for name in fields):
            raise ProtocolError('Update contains no supported product fields')
        columns = [('id', 9)] + [(name, column_types[name]) for name in fields]
        record = Record('root', columns, [{'id': product_id, **fields}])
        response = request(self.session, self._command(namespace, 'update'), encode_records([record]))
        if response.is_error:
            raise ServerError(response.result)
        return response
