"""Tests du décodeur de carte (messages MAP_<mac> synthétiques)."""
from __future__ import annotations

import struct
import zlib

import pytest
from custom_components.neatsvor_s600.map_decoder import (
    DOCK_RGB,
    ROBOT_RGB,
    TRAIL_RGB,
    decode_map,
    render_png,
    to_cell,
)
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


# --- Suivi du robot : trajet, repère des coordonnées, superposition -------------------------

NEG_ONE = (1 << 64) - 1  # -1 tel qu'il est encodé en varint 64 bits
FLOOR_ROOM_1 = (255, 170, 102)  # couleur du sol de la pièce 1 dans la palette


def _point(x: int, y: int) -> bytes:
    return length_delimited_field(2, varint_field(1, x) + varint_field(2, y))


def _trail_chunk(*groups: list[tuple[int, int]]) -> bytes:
    """Un groupe 6.4 : type, puis chaque groupe de points précédé d'un séparateur (-1, -1)."""
    body = varint_field(1, 1)
    for points in groups:
        body += _point(NEG_ONE, NEG_ONE)
        for x, y in points:
            body += _point(x, y)
    return body


def build_tracking_message(
    width: int = 40,
    height: int = 30,
    robot: tuple[int, int, int] = (200, 150, 90),
    dock: tuple[int, int] = (100, 150),
    trail_chunks: list[bytes] | None = None,
) -> bytes:
    """Carte d'une seule pièce (sol partout) avec robot, base et trajet."""
    grid = bytes([_pixel(1, 1)] * (width * height))
    grid_msg = length_delimited_field(2, grid) + length_delimited_field(
        5, varint_field(1, dock[0]) + varint_field(2, dock[1])
    )
    pose = length_delimited_field(
        2, varint_field(1, robot[0]) + varint_field(2, robot[1]) + varint_field(3, robot[2])
    )
    chunks = b"".join(length_delimited_field(4, chunk) for chunk in trail_chunks or [])
    map_data = (
        varint_field(1, 7)
        + varint_field(2, width)
        + varint_field(3, height)
        + varint_field(4, 5)
        + length_delimited_field(5, grid_msg)
        + length_delimited_field(6, pose + chunks)
    )
    any_msg = length_delimited_field(1, b"type.googleapis.com/sweeper.MapData") + length_delimited_field(
        2, map_data
    )
    return length_delimited_field(1, varint_field(1, 1)) + length_delimited_field(2, any_msg)


def _decode_png(png: bytes) -> tuple[int, int, list[bytes]]:
    width, height = struct.unpack(">II", png[16:24])
    idat_start = png.index(b"IDAT") + 4
    idat_len = struct.unpack(">I", png[idat_start - 8 : idat_start - 4])[0]
    raw = zlib.decompress(png[idat_start : idat_start + idat_len])
    stride = 1 + width * 4
    return width, height, [raw[y * stride + 1 : (y + 1) * stride] for y in range(height)]


def _rgb_at(rows: list[bytes], x: int, y: int) -> tuple[int, int, int]:
    return tuple(rows[y][x * 4 : x * 4 + 3])


def test_decode_map_without_trail_has_empty_tuple():
    assert decode_map(build_map_message()).trail == ()
    assert decode_map(build_tracking_message()).trail == ()


def test_decode_map_trail_segments_and_signed_values():
    message = build_tracking_message(
        robot=(2255, 2139, (1 << 64) - 164),  # angle -164 encodé en varint 64 bits
        trail_chunks=[
            _trail_chunk([(2256, 2188), (2258, 2199)]),
            _trail_chunk([(2460, 2195)]),
        ],
    )
    result = decode_map(message)
    assert result.robot == (2255, 2139, -164)
    assert result.trail == (((2256, 2188), (2258, 2199)), ((2460, 2195),))


def test_decode_map_trail_break_inside_a_group_starts_a_new_segment():
    message = build_tracking_message(
        trail_chunks=[_trail_chunk([(10, 20), (30, 40)], [(50, 60)])],
    )
    assert decode_map(message).trail == (((10, 20), (30, 40)), ((50, 60),))


def test_to_cell_uses_ten_units_per_cell_and_zero_origin():
    assert to_cell(2255, 2139) == pytest.approx((225.5, 213.9))
    assert to_cell(0, 0) == (0, 0)


def test_render_png_scale_and_overlay():
    message = build_tracking_message(
        robot=(200, 150, 90),  # cellule (20, 15), cap vers le haut
        dock=(100, 150),  # cellule (10, 15)
        trail_chunks=[_trail_chunk([(60, 60), (160, 60)])],  # cellules (6, 6) -> (16, 6)
    )
    result = decode_map(message)

    plain_png = render_png(result, scale=2)
    assert render_png(result, scale=2, overlay=False) == plain_png  # pas de tracé par défaut
    width, height, plain = _decode_png(plain_png)
    assert (width, height) == (80, 60)

    _, _, drawn = _decode_png(render_png(result, scale=2, overlay=True))
    assert _rgb_at(plain, 22, 12) == FLOOR_ROOM_1
    assert _rgb_at(drawn, 22, 12) == TRAIL_RGB  # milieu du trajet
    assert _rgb_at(drawn, 20, 30) == DOCK_RGB  # base
    assert _rgb_at(drawn, 44, 30) == ROBOT_RGB  # corps du robot, hors de la ligne de cap
    assert _rgb_at(drawn, 40, 26) == (255, 255, 255)  # cap vers le haut (angle 90 degrés)


def test_render_png_overlay_ignores_points_outside_the_grid():
    # Robot, base et trajet hors de la petite grille de 6 x 4 : rien ne doit planter.
    result = decode_map(build_map_message())
    assert render_png(result, overlay=True) == render_png(result)
