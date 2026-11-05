"""Tests du décodeur de carte (messages MAP_<mac> synthétiques)."""
from __future__ import annotations

import struct
import zlib

import pytest
from custom_components.neatsvor_s600.map_decoder import decode_map, render_png
from custom_components.neatsvor_s600.protobuf_lite import (
    length_delimited_field,
    varint_field,
)

WIDTH, HEIGHT = 6, 4


def _pixel(room: int, kind: int) -> int:
    return (room << 2) | kind


def build_map_message(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """Construit un SdkCom.MqttMsg{Any{sweeper.MapData}} minimal (format observé)."""
    row = [_pixel(0, 0), _pixel(1, 2)] + [_pixel(1, 1)] * 2 + [_pixel(2, 1)] * 2
    grid = bytes(row * height)[: width * height]
    grid_msg = varint_field(1, width) + varint_field(3, height) + length_delimited_field(2, grid)
    rooms = b"".join(
        length_delimited_field(8, varint_field(1, rid) + length_delimited_field(2, name.encode()))
        for rid, name in ((1, "Salon"), (2, "Cuisine"))
    )
    map_data = length_delimited_field(5, grid_msg) + rooms
    any_msg = length_delimited_field(1, b"type.googleapis.com/sweeper.MapData") + length_delimited_field(
        2, map_data
    )
    return length_delimited_field(1, varint_field(1, 1)) + length_delimited_field(2, any_msg)


def test_decode_map_dimensions_grid_and_rooms():
    result = decode_map(build_map_message())
    assert (result.width, result.height) == (WIDTH, HEIGHT)
    assert len(result.grid) == WIDTH * HEIGHT
    assert result.rooms == {1: "Salon", 2: "Cuisine"}


def test_render_png_is_valid_rgba():
    png = render_png(decode_map(build_map_message()))
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    ihdr = png[16:29]
    assert struct.unpack(">IIBBBBB", ihdr) == (WIDTH, HEIGHT, 8, 6, 0, 0, 0)
    idat_start = png.index(b"IDAT") + 4
    idat_len = struct.unpack(">I", png[idat_start - 8 : idat_start - 4])[0]
    raw = zlib.decompress(png[idat_start : idat_start + idat_len])
    assert len(raw) == HEIGHT * (1 + WIDTH * 4)
    assert raw[1:5] == b"\x00\x00\x00\x00"  # pixel vide : transparent
    assert raw[5 + 3] == 255  # mur : opaque


@pytest.mark.parametrize(
    "payload",
    [b"", length_delimited_field(2, b""), length_delimited_field(1, b"x")],
    ids=["empty", "empty-body", "no-body"],
)
def test_decode_map_rejects_garbage(payload):
    with pytest.raises(ValueError):
        decode_map(payload)
