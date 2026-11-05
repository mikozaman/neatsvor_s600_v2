"""Décodage et rendu de la carte (topic MAP_<mac>, message sweeper.MapData).

Structure établie à partir d'une capture réelle (31 oct 2026) :

    SdkCom.MqttMsg { header(1), body(2) = google.protobuf.Any { type_url(1), value(2) } }
    value = sweeper.MapData
        champ 5  -> sous-message de grille ; son champ 2 = pixels (1 octet/pixel)
        champ 8  -> noms des pièces (répété)

Pixel : ``(room_id << 2) | type`` avec type 1 = sol, 2 = mur, 0 = vide.
Largeur/hauteur observées : 364 x 485.

Ce qui n'est PAS validé : l'emplacement exact des champs largeur/hauteur
(déduits ici en cherchant deux varints dont le produit égale la taille de la
grille) et le format exact des entrées de noms de pièces (champ 8, lu de
façon tolérante). La trajectoire, la position du robot et les zones ne sont
pas encore décodées. Le rendu n'applique aucune rotation/symétrie.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from .protobuf_lite import decode_fields, first

PIXEL_EMPTY = 0
PIXEL_FLOOR = 1
PIXEL_WALL = 2

_MAX_ROOMS = 64
_MAX_PIXELS = 4_000_000

# Palette cyclique (RGB) par identifiant de pièce.
_PALETTE = [
    (102, 178, 255), (255, 170, 102), (130, 210, 130), (230, 130, 190),
    (190, 160, 240), (240, 220, 110), (110, 210, 205), (220, 120, 110),
    (160, 190, 110), (150, 150, 230), (235, 170, 150), (120, 190, 170),
]
_WALL_RGB = (45, 45, 45)
_OTHER_RGB = (120, 120, 120)


@dataclass(frozen=True)
class MapData:
    """Carte décodée."""

    width: int
    height: int
    grid: bytes = field(repr=False)
    rooms: dict[int, str] = field(default_factory=dict)


def _find_dimensions(grid_fields: dict[int, list], size: int) -> tuple[int, int]:
    ints = [
        v
        for _, values in sorted(grid_fields.items())
        for v in values
        if isinstance(v, int) and v > 0
    ]
    for i, width in enumerate(ints):
        for height in ints[i + 1 :]:
            if width * height == size:
                return width, height
    raise ValueError("Map dimensions not found in grid message")


def _parse_rooms(entries: list) -> dict[int, str]:
    rooms: dict[int, str] = {}
    for entry in entries[:_MAX_ROOMS]:
        if not isinstance(entry, bytes):
            continue
        try:
            sub = decode_fields(entry)
        except ValueError:
            continue
        ids = [v for vals in sub.values() for v in vals if isinstance(v, int)]
        names = []
        for vals in sub.values():
            for v in vals:
                if isinstance(v, bytes):
                    try:
                        text = v.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    if text and text.isprintable():
                        names.append(text)
        if ids and names:
            rooms[ids[0]] = names[0]
    return rooms


def decode_map(raw: bytes) -> MapData:
    """Décode un message MAP déjà décompressé (gzip retiré)."""
    top = decode_fields(raw)
    body = first(top, 2)
    if not isinstance(body, bytes):
        raise ValueError("MAP message has no body")
    value = first(decode_fields(body), 2)
    if not isinstance(value, bytes):
        raise ValueError("MAP body has no Any value")
    map_fields = decode_fields(value)
    grid_msg = first(map_fields, 5)
    if not isinstance(grid_msg, bytes):
        raise ValueError("MAP message has no grid")
    grid_fields = decode_fields(grid_msg)
    grid = first(grid_fields, 2)
    if not isinstance(grid, bytes) or not grid or len(grid) > _MAX_PIXELS:
        raise ValueError("MAP grid missing or oversized")
    width, height = _find_dimensions(grid_fields, len(grid))
    return MapData(width, height, grid, _parse_rooms(map_fields.get(8, [])))


def _lookup_tables() -> tuple[bytes, bytes, bytes, bytes]:
    red, green, blue, alpha = bytearray(256), bytearray(256), bytearray(256), bytearray(256)
    for value in range(256):
        kind, room = value & 3, value >> 2
        if kind == PIXEL_EMPTY:
            continue  # transparent
        if kind == PIXEL_FLOOR:
            rgb = _PALETTE[room % len(_PALETTE)]
        elif kind == PIXEL_WALL:
            rgb = _WALL_RGB
        else:
            rgb = _OTHER_RGB
        red[value], green[value], blue[value], alpha[value] = (*rgb, 255)
    return bytes(red), bytes(green), bytes(blue), bytes(alpha)


_TABLES = _lookup_tables()


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def render_png(map_data: MapData) -> bytes:
    """Rend la carte en PNG RGBA sans dépendance externe (pas de Pillow)."""
    width, height, grid = map_data.width, map_data.height, map_data.grid
    rgba = bytearray(len(grid) * 4)
    for offset, table in enumerate(_TABLES):
        rgba[offset::4] = grid.translate(table)
    stride = width * 4
    rows = b"".join(b"\x00" + bytes(rgba[y * stride : (y + 1) * stride]) for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows, 6))
        + _chunk(b"IEND", b"")
    )
