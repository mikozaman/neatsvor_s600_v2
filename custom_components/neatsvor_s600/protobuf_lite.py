"""Small, bounds-checked protobuf wire codec for the fields used by Neatsvor."""
from __future__ import annotations

from typing import Any

_MAX_VARINT_BYTES = 10
_MAX_MESSAGE_BYTES = 1_000_000


def _read_varint(data: bytes, index: int) -> tuple[int, int]:
    result = 0
    for offset in range(_MAX_VARINT_BYTES):
        if index >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << (7 * offset)
        if not byte & 0x80:
            return result, index
    raise ValueError("Protobuf varint exceeds 10 bytes")


def decode_fields(data: bytes) -> dict[int, list[Any]]:
    """Decode protobuf wire types 0, 1, 2 and 5 with strict bounds checks."""
    if len(data) > _MAX_MESSAGE_BYTES:
        raise ValueError("Protobuf message exceeds size limit")
    result: dict[int, list[Any]] = {}
    index = 0
    while index < len(data):
        tag, index = _read_varint(data, index)
        field_number, wire_type = tag >> 3, tag & 0x7
        if field_number == 0:
            raise ValueError("Invalid protobuf field number 0")
        if wire_type == 0:
            value, index = _read_varint(data, index)
        elif wire_type == 2:
            field_len, index = _read_varint(data, index)
            end = index + field_len
            if end > len(data):
                raise ValueError("Truncated length-delimited protobuf field")
            value = data[index:end]
            index = end
        elif wire_type in (1, 5):
            width = 8 if wire_type == 1 else 4
            end = index + width
            if end > len(data):
                raise ValueError("Truncated fixed-width protobuf field")
            value = data[index:end]
            index = end
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
        result.setdefault(field_number, []).append(value)
    return result


def first(fields: dict[int, list[Any]], field_number: int) -> Any | None:
    values = fields.get(field_number)
    return values[0] if values else None


def _tag(field_number: int, wire_type: int) -> bytes:
    if not 1 <= field_number < (1 << 29):
        raise ValueError("Invalid protobuf field number")
    return _encode_varint((field_number << 3) | wire_type)


def _encode_varint(value: int) -> bytes:
    if not isinstance(value, int) or value < 0 or value >= (1 << 64):
        raise ValueError("Protobuf varint must be an unsigned 64-bit integer")
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def length_delimited_field(field_number: int, payload: bytes) -> bytes:
    return _tag(field_number, 2) + _encode_varint(len(payload)) + payload


def varint_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, 0) + _encode_varint(value)


def packed_varint_field(field_number: int, values: list[int]) -> bytes:
    payload = b"".join(_encode_varint(value) for value in values)
    return length_delimited_field(field_number, payload)
