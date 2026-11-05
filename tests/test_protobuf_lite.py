import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).parents[1] / "custom_components" / "neatsvor_s600" / "protobuf_lite.py"
SPEC = importlib.util.spec_from_file_location("protobuf_lite", MODULE)
protobuf_lite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protobuf_lite)
decode_fields = protobuf_lite.decode_fields
first = protobuf_lite.first
length_delimited_field = protobuf_lite.length_delimited_field
packed_varint_field = protobuf_lite.packed_varint_field
varint_field = protobuf_lite.varint_field


class ProtobufLiteTests(unittest.TestCase):
    def test_round_trip_supported_fields(self):
        payload = varint_field(1, 300) + length_delimited_field(2, b"abc")
        fields = decode_fields(payload)
        self.assertEqual(first(fields, 1), 300)
        self.assertEqual(first(fields, 2), b"abc")

    def test_packed_varints(self):
        fields = decode_fields(packed_varint_field(3, [1, 2, 300]))
        self.assertEqual(first(fields, 3), bytes([1, 2, 0xAC, 0x02]))

    def test_negative_int32_is_ten_byte_twos_complement(self):
        encoded = varint_field(2, -1)
        self.assertEqual(encoded, b"\x10" + b"\xff" * 9 + b"\x01")
        self.assertEqual(first(decode_fields(encoded), 2), (1 << 64) - 1)

    def test_rejects_out_of_range_varint(self):
        with self.assertRaises(ValueError):
            varint_field(1, 1 << 64)

    def test_rejects_truncated_varint(self):
        with self.assertRaisesRegex(ValueError, "Truncated protobuf varint"):
            decode_fields(b"\x80")

    def test_rejects_truncated_length_delimited(self):
        with self.assertRaisesRegex(ValueError, "Truncated length-delimited"):
            decode_fields(b"\x0a\x05x")

    def test_rejects_invalid_field_zero(self):
        with self.assertRaisesRegex(ValueError, "Invalid protobuf field number 0"):
            decode_fields(b"\x00")

    def test_rejects_unsupported_wire_type(self):
        with self.assertRaisesRegex(ValueError, "Unsupported protobuf wire type: 3"):
            decode_fields(b"\x0b")

    def test_rejects_overlong_varint(self):
        with self.assertRaisesRegex(ValueError, "exceeds 10 bytes"):
            decode_fields(b"\x80" * 10 + b"\x01")


if __name__ == "__main__":
    unittest.main()
