"""Décodage et rendu de la carte (topic MAP_<mac>, message sweeper.MapData).

Structure confirmée sur une capture réelle (S600, 5 nov 2026) :

    SdkCom.MqttMsg { header(1) (champ 2 = adresse MAC), body(2) = Any { type_url(1), value(2) } }
    value = sweeper.MapData
        1  = identifiant de carte          2 = largeur (364)      3 = hauteur (485)
        4  = résolution (5)
        5  = { 2: pixels (largeur*hauteur octets), 3, 4, 5: {1: x, 2: y} }  (5.5 = base, à confirmer)
        6  = { 2: {1: x, 2: y, 3: angle} (robot, à confirmer), 4: trajectoire ... }
        8  = { 1: [ {1: id, 2: nom} ... ],
               2: [ {1: id, 2: fan_level, 3: water_level, 4: clean_times, 5: ?} ... ] }
        9  = zones interdites / murs virtuels {1: x1, 2: y1, 3: x2, 4: y2}

Pixel : ``(room_id << 2) | type`` avec type 1 = sol, 2 = mur (mur rattaché à sa pièce),
0 = vide. Réglages par pièce (8.2), confirmés avec l'app : fan_level (jusqu'à 4 au moins),
water_level, clean_times ; le champ 5 (toujours 2 observé) reste inconnu.

Non décodés/validés : unité et origine des coordonnées (robot, base, trajectoire, zones),
donc rien n'est dessiné dessus. Le rendu n\'applique aucune rotation/symétrie.
"""
from __future__ import annotations

import struct
import unicodedata
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
    room_settings: dict[int, dict[str, int | None]] = field(default_factory=dict)
    map_id: int | None = None
    resolution: int | None = None
    dock: tuple[int, int] | None = None
    robot: tuple[int, int, int | None] | None = None


def _sub(blob) -> dict[int, list]:
    if not isinstance(blob, bytes):
        return {}
    try:
        return decode_fields(blob)
    except ValueError:
        return {}


def _parse_rooms(blob) -> tuple[dict[int, str], dict[int, dict[str, int | None]]]:
    rooms: dict[int, str] = {}
    settings: dict[int, dict[str, int | None]] = {}
    fields = _sub(blob)
    for entry in fields.get(1, [])[:_MAX_ROOMS]:
        sub = _sub(entry)
        room_id, name = first(sub, 1), first(sub, 2)
        if isinstance(room_id, int) and isinstance(name, bytes):
            rooms[room_id] = name.decode("utf-8", "replace")
    for entry in fields.get(2, [])[:_MAX_ROOMS]:
        sub = _sub(entry)
        room_id = first(sub, 1)
        if isinstance(room_id, int):
            settings[room_id] = {
                "fan_level": first(sub, 2),
                "water_level": first(sub, 3),
                "clean_times": first(sub, 4),
                "unknown_5": first(sub, 5),
            }
    return rooms, settings


def _xy(blob) -> tuple | None:
    sub = _sub(blob)
    x, y = first(sub, 1), first(sub, 2)
    if isinstance(x, int) and isinstance(y, int):
        return x, y, first(sub, 3)
    return None


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
    grid_fields = _sub(first(map_fields, 5))
    grid = first(grid_fields, 2)
    if not isinstance(grid, bytes) or not grid or len(grid) > _MAX_PIXELS:
        raise ValueError("MAP grid missing or oversized")
    width, height = first(map_fields, 2), first(map_fields, 3)
    if not (isinstance(width, int) and isinstance(height, int)) or width * height != len(grid):
        raise ValueError("MAP dimensions do not match the grid size")
    rooms, settings = _parse_rooms(first(map_fields, 8))
    dock = _xy(first(grid_fields, 5))
    robot = _xy(first(_sub(first(map_fields, 6)), 2))
    return MapData(
        width,
        height,
        grid,
        rooms,
        settings,
        first(map_fields, 1) if isinstance(first(map_fields, 1), int) else None,
        first(map_fields, 4) if isinstance(first(map_fields, 4), int) else None,
        dock[:2] if dock else None,
        robot,
    )


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


def _norm(text: str) -> str:
    """Minuscules, sans accents, espaces normalisés : « Séjour » == « sejour »."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)
    )
    return " ".join(stripped.casefold().split())


def resolve_rooms(known: dict[int, str], items: list[int | str]) -> list[int]:
    """Convertit des identifiants et/ou des noms de pièces en identifiants.

    Un nom est reconnu sans tenir compte de la casse ni des accents ; à défaut de
    correspondance exacte, une sous-chaîne unique suffit (« garcons » -> « Chambre Garçons »).
    Lève ValueError (message lisible) pour un nom inconnu, ambigu, ou si la carte est vide.
    """
    by_name = {_norm(name): room_id for room_id, name in known.items()}
    resolved: list[int] = []
    for item in items:
        if isinstance(item, int) or str(item).strip().isdigit():
            room_id = int(item)
        else:
            key = _norm(item)
            if not known:
                raise ValueError(f"Room '{item}' unknown: the map has not been received yet")
            if key in by_name:
                room_id = by_name[key]
            else:
                hits = [rid for name, rid in by_name.items() if key and key in name]
                if len(hits) != 1:
                    kind = "ambiguous" if hits else "unknown"
                    available = ", ".join(sorted(known.values()))
                    raise ValueError(f"Room '{item}' is {kind}. Available rooms: {available}")
                room_id = hits[0]
        if room_id not in resolved:
            resolved.append(room_id)
    return resolved
