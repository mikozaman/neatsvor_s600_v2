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
    """MqttMsg{Any{sweeper.MapData}} avec la structure d'une capture réelle."""
    row = [_pixel(0, 0), _pixel(1, 2)] + [_pixel(1, 1)] * 2 + [_pixel(2, 1)] * 2
    grid = bytes(row * height)[: width * height]
    grid_msg = (
        length_delimited_field(2, grid)
        + varint_field(3, 1)
        + varint_field(4, 1250750)
        + length_delimited_field(5, varint_field(1, 2223) + varint_field(2, 2132))
    )
    names = b"".join(
        length_delimited_field(1, varint_field(1, rid) + length_delimited_field(2, name.encode()))
        for rid, name in ((1, "Salon"), (2, "Cuisine"))
    )
    settings = b"".join(
        length_delimited_field(
            2,
            varint_field(1, rid)
            + varint_field(2, fan)
            + varint_field(3, 3)
            + varint_field(4, times)
            + varint_field(5, 2),
        )
        for rid, fan, times in ((1, 4, 1), (2, 3, 2))
    )
    robot = length_delimited_field(
        2, varint_field(1, 2256) + varint_field(2, 2132) + varint_field(3, 154)
    )
    map_data = (
        varint_field(1, 139)
        + varint_field(2, width)
        + varint_field(3, height)
        + varint_field(4, 5)
        + length_delimited_field(5, grid_msg)
        + length_delimited_field(6, robot)
        + length_delimited_field(8, names + settings)
    )
    any_msg = length_delimited_field(1, b"type.googleapis.com/sweeper.MapData") + length_delimited_field(
        2, map_data
    )
    return length_delimited_field(1, varint_field(1, 1)) + length_delimited_field(2, any_msg)


def test_decode_map_dimensions_grid_and_rooms():
    result = decode_map(build_map_message())
    assert (result.width, result.height) == (WIDTH, HEIGHT)
    assert len(result.grid) == WIDTH * HEIGHT
    assert result.rooms == {1: "Salon", 2: "Cuisine"}
    assert result.room_settings == {
        1: {"fan_level": 4, "water_level": 3, "clean_times": 1, "unknown_5": 2},
        2: {"fan_level": 3, "water_level": 3, "clean_times": 2, "unknown_5": 2},
    }
    assert (result.map_id, result.resolution) == (139, 5)
    assert result.dock == (2223, 2132)
    assert result.robot == (2256, 2132, 154)


def test_decode_map_rejects_wrong_dimensions():
    with pytest.raises(ValueError):
        decode_map(build_map_message(width=7))  # 7*4 != taille de la grille


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
