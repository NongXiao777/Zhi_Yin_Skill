import importlib.util
from decimal import Decimal
import gzip
from pathlib import Path
import struct
import unittest
import uuid
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('zying_transport', ROOT / 'scripts' / 'zying_transport.py')
transport = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = transport
SPEC.loader.exec_module(transport)


class NativeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.session = transport.Session('unused', 1,
            uuid.UUID('00112233-4455-6677-8899-aabbccddeeff'),
            uuid.UUID('11223344-5566-7788-99aa-bbccddeeff00'), 12, 12980)

    def test_detail_parameter_wire_bytes(self):
        expected = b'\x02id\x09\x00\x00\x00954521907'
        self.assertEqual(transport.encode_parameters({'id': 954521907}), expected)

    def test_packet_has_mode_and_vendor_header_order(self):
        payload = b'payload'
        packet = transport.build_packet(self.session, 'sale.detail', payload)
        self.assertEqual(packet[:1], b'M')
        self.assertEqual(struct.unpack('<i', packet[1:5])[0], len(packet) - 5)
        self.assertEqual(packet[5:13], struct.pack('<ii', 12, 12980))
        self.assertEqual(packet[13:29], self.session.client_id.bytes_le)
        self.assertEqual(packet[29:45], self.session.token.bytes_le)
        self.assertEqual(packet[45:], b'\x0bsale.detailpayload')

    def test_decimal_layout_matches_dotnet_getbits(self):
        encoded = transport.decimal_bytes(Decimal('-12.50'))
        self.assertEqual(encoded, struct.pack('<IIII', 1250, 0, 0, 0x80020000))
        self.assertEqual(transport.read_decimal(transport.Reader(encoded)), Decimal('-12.50'))

    def test_update_record_preserves_typed_minimal_columns(self):
        record = transport.Record('root', [('id', 9), ('sale_stock', 18)],
                                  [{'id': 951393413, 'sale_stock': '[{"key":"A","money":7.0}]'}])
        encoded = transport.encode_records([record])
        decoded = transport.read_records(transport.Reader(encoded))
        self.assertEqual(decoded['root'].columns, record.columns)
        self.assertEqual(decoded['root'].rows, record.rows)

    def test_roundtrip_scalar_and_array_records(self):
        columns = [('cost', 15), ('flags', 3), ('ids', 109), ('texts', 118)]
        rows = [{'cost': Decimal('1.2300'), 'flags': True, 'ids': [1, -2], 'texts': ['中文', '']}]
        record = transport.Record('root', columns, rows)
        decoded = transport.read_records(transport.Reader(transport.encode_records([record])))
        self.assertEqual(decoded['root'].rows, rows)

    def test_numeric_arrays_use_vendor_uint16_count(self):
        self.assertEqual(transport.encode_value(109, [1, 2]), struct.pack('<Hii', 2, 1, 2))
        self.assertEqual(transport.encode_value(111, [1, 2]), struct.pack('<Hqq', 2, 1, 2))
        self.assertEqual(transport.encode_value(115, [Decimal('1')]),
                         b'\x01\x00' + transport.decimal_bytes(Decimal('1')))
        self.assertEqual(transport.encode_value(106, [1, 2]), b'\x02\x00\x00\x00\x01\x02')

    def test_string_array_count_limit_is_checked_on_decode(self):
        with self.assertRaises(transport.ProtocolError):
            transport.read_value(transport.Reader(struct.pack('<H', 10001)), 118)

    def test_response_gzip_preserves_identity_and_decodes_record(self):
        head = (struct.pack('<i', 13) + self.session.client_id.bytes_le + self.session.token.bytes_le)
        payload = struct.pack('<qB', 1, 0) + transport.encode_text('ok') + transport.encode_records([])
        response = transport.decode_response(head + b'ZG' + gzip.compress(payload), self.session)
        self.assertEqual(response.protocol_version, 13)
        self.assertEqual(response.message, 'ok')
        self.assertFalse(response.is_error)

    def test_mismatched_session_is_rejected(self):
        body = struct.pack('<i', 13) + uuid.UUID(int=0).bytes_le + self.session.token.bytes_le
        body += struct.pack('<qB', 1, 0) + transport.encode_text('ok') + b'\0'
        with self.assertRaises(transport.ProtocolError):
            transport.decode_response(body, self.session)

    def test_schema_mismatch_cannot_silently_drop_fields(self):
        record = transport.Record('root', [('id', 9)], [{'id': 1, 'extra': 'x'}])
        with self.assertRaises(transport.ProtocolError):
            transport.encode_records([record])

    def test_response_properties_are_preserved(self):
        body = struct.pack('<i', 13) + self.session.client_id.bytes_le + self.session.token.bytes_le
        body += struct.pack('<qB', 1, 0) + transport.encode_text('ok')
        body += transport.encode_name('page') + transport.encode_text('1') + b'\0'
        result = transport.decode_response(body, self.session, 1)
        self.assertEqual(result.properties, {'page': '1'})

    def test_unknown_mode_never_sends_a_request(self):
        self.session.mode = 'TLS'
        with self.assertRaises(transport.ProtocolError):
            transport.NativeClient(self.session)

    def test_client_read_preserves_records_and_namespace(self):
        record = transport.Record('root', [('sale_id', 9)], [{'sale_id': 951393413}])
        response = transport.Response(13, 1, False, 'ok', {}, {'root': record})
        with patch.object(transport, 'request', return_value=response) as sender:
            result = transport.NativeClient(self.session).read_detail('sale', 951393413)
        self.assertEqual(result, {'root': [{'sale_id': 951393413}]})
        self.assertEqual(sender.call_args.args[1], 'sale.detail')

    def test_client_server_error_does_not_expose_message(self):
        response = transport.Response(13, -1, True, 'secret-token-value', {}, {})
        with patch.object(transport, 'request', return_value=response):
            with self.assertRaises(transport.ServerError) as error:
                transport.NativeClient(self.session).read_detail('sale', 951393413)
        self.assertNotIn('secret-token-value', str(error.exception))

    def test_error_response_can_end_without_record_count(self):
        body = struct.pack('<i', 13) + self.session.client_id.bytes_le + self.session.token.bytes_le
        body += struct.pack('<qB', -9, 1) + transport.encode_text('account rejected')
        result = transport.decode_response(body, self.session)
        self.assertEqual(result.result, -9)
        self.assertTrue(result.is_error)
        self.assertEqual(result.records, {})

    def test_m_mode_reads_count_and_length_with_fragmented_tcp(self):
        head = struct.pack('<i', 13) + self.session.client_id.bytes_le + self.session.token.bytes_le
        body = head + struct.pack('<qB', 1, 0) + transport.encode_text('ok')
        body += transport.encode_name('page') + transport.encode_text('1') + b'\0'
        wire = bytearray(b'c\1' + struct.pack('<i', len(body)) + body)
        connection = Mock()

        def recv(count):
            size = min(count, 3)
            data = bytes(wire[:size])
            del wire[:size]
            return data

        connection.recv.side_effect = recv
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        with patch.object(transport.socket, 'create_connection', return_value=connection):
            result = transport.request(self.session, 'sale.detail', b'params')
        self.assertEqual(result.properties, {'page': '1'})
        self.assertEqual(result.message, 'ok')
        self.assertEqual(self.session.protocol_version, 13)
        connection.sendall.assert_called_once()


if __name__ == '__main__':
    unittest.main()
