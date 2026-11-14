"""Décodage et rendu de la carte (topic MAP_<mac>, message sweeper.MapData).

Structure confirmée sur des captures réelles (S600, 5 et 13 nov 2026) :

    SdkCom.MqttMsg { header(1) (champ 2 = adresse MAC), body(2) = Any { type_url(1), value(2) } }
    value = sweeper.MapData
        1  = identifiant de carte          2 = largeur (364)      3 = hauteur (485)
        4  = résolution (5 ; 5 cm par cellule)
        5  = { 2: pixels (largeur*hauteur octets), 3, 4, 5: {1: x, 2: y} (base) }
        6  = { 2: {1: x, 2: y, 3: angle} (robot),
               3: nombre de points du trajet (séparateurs inclus),
               4: [ {1: type, 2: [ {1: x, 2: y} ... ]} ... ] (trajet) }
        7  = zone du dernier nettoyage par zone (polygone de 4 points)
        8  = { 1: [ {1: id, 2: nom} ... ],
               2: [ {1: id, 2: fan_level, 3: water_level, 4: clean_times, 5: ?} ... ] }
        9  = { 1: [ {1: x1, 2: y1, 3: x2, 4: y2} ... ] (murs virtuels),
               3: zone interdite au lavage (polygone) }

Pixel : ``(room_id << 2) | type`` avec type 1 = sol, 2 = mur (mur rattaché à sa pièce),
0 = vide. Réglages par pièce (8.2), confirmés avec l'app : fan_level (jusqu'à 4 au moins),
water_level, clean_times ; le champ 5 (toujours 2 observé) reste inconnu.

Repère des coordonnées (validé le 13 nov 2026 en superposant une capture de l'app Joylife, la
grille et les trames) : un seul repère pour le robot, la base, le trajet, les zones et les murs
virtuels.

  - x vers la droite, y vers le bas, comme la grille ; aucune rotation ni symétrie ;
  - cellule = coordonnée / CELL_UNITS, origine (0, 0). Avec la résolution 5 (5 cm par cellule),
    une unité vaut environ 5 mm ;
  - angle en degrés, sens anti-horaire à l'écran : direction = (cos a, -sin a) (relevé sur
    quelques points seulement, à confirmer sur un long trajet).

Trajet : polyligne simplifiée (seuls les sommets sont envoyés). Le point (-1, -1) sépare les
segments. Il n'est pas prolongé pendant le retour à la base : pour suivre le robot en direct,
utiliser la position (champ 6.2). La position de la base n'est fiable qu'une fois le robot posé
dessus (elle peut être décalée pendant un nettoyage).

Le rendu n'applique aucune rotation/symétrie. Un tracé du robot, de son trajet et de la base peut
être superposé (``overlay=True``).
"""
from __future__ import annotations

import math
import struct
import unicodedata
import zlib
from dataclasses import dataclass, field

from .protobuf_lite import decode_fields, first

PIXEL_EMPTY = 0
PIXEL_FLOOR = 1
PIXEL_WALL = 2

# Unités de coordonnées par cellule de la grille (validé : cellule = coordonnée / 10).
CELL_UNITS = 10
# Séparateur de segments dans le trajet.
TRAIL_BREAK = (-1, -1)

_MAX_ROOMS = 64
_MAX_PIXELS = 4_000_000
_MAX_TRAIL_CHUNKS = 2_000
_MAX_TRAIL_POINTS = 20_000
_MAX_SCALE = 8

# Palette cyclique (RGB) par identifiant de pièce.
_PALETTE = [
    (102, 178, 255), (255, 170, 102), (130, 210, 130), (230, 130, 190),
    (190, 160, 240), (240, 220, 110), (110, 210, 205), (220, 120, 110),
    (160, 190, 110), (150, 150, 230), (235, 170, 150), (120, 190, 170),
]
_WALL_RGB = (45, 45, 45)
_OTHER_RGB = (120, 120, 120)

# Couleurs de la superposition.
ROBOT_RGB = (20, 90, 255)
TRAIL_RGB = (0, 60, 170)
DOCK_RGB = (0, 170, 70)
_OUTLINE_RGB = (255, 255, 255)
_ROBOT_RADIUS_CELLS = 3.5  # robot d'environ 35 cm de diamètre


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
    # Segments du trajet : chaque segment est une suite de sommets (x, y) en unités de coordonnées.
    trail: tuple[tuple[tuple[int, int], ...], ...] = ()


def to_cell(x: float, y: float) -> tuple[float, float]:
    """Convertit des coordonnées (robot, base, trajet, zones) en position dans la grille."""
    return x / CELL_UNITS, y / CELL_UNITS


def _signed(value: int) -> int:
    """Entier protobuf 64 bits non signé -> signé (les -1 du trajet, les angles négatifs)."""
    return value - (1 << 64) if value >= (1 << 63) else value


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
    x, y, angle = first(sub, 1), first(sub, 2), first(sub, 3)
    if isinstance(x, int) and isinstance(y, int):
        return _signed(x), _signed(y), _signed(angle) if isinstance(angle, int) else angle
    return None


def _parse_trail(robot_fields: dict[int, list]) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Segments du trajet (champ 6.4). Un groupe 6.4 = un segment ; (-1, -1) en ouvre un autre."""
    segments: list[tuple[tuple[int, int], ...]] = []
    for chunk in robot_fields.get(4, [])[:_MAX_TRAIL_CHUNKS]:
        current: list[tuple[int, int]] = []
        for point in _sub(chunk).get(2, [])[:_MAX_TRAIL_POINTS]:
            xy = _xy(point)
            if xy is None:
                continue
            if xy[:2] == TRAIL_BREAK:
                if current:
                    segments.append(tuple(current))
                    current = []
                continue
            current.append((xy[0], xy[1]))
        if current:
            segments.append(tuple(current))
    return tuple(segments)


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
    robot_fields = _sub(first(map_fields, 6))
    robot = _xy(first(robot_fields, 2))
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
        trail=_parse_trail(robot_fields),
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


def _scaled_grid(grid: bytes, width: int, height: int, scale: int) -> bytes:
    """Agrandit la grille d'un facteur entier (plus proche voisin)."""
    if scale == 1:
        return grid
    out = bytearray()
    for y in range(height):
        row = grid[y * width : (y + 1) * width]
        wide = bytearray(width * scale)
        for k in range(scale):
            wide[k::scale] = row
        out += bytes(wide) * scale
    return bytes(out)


def _put(buf: bytearray, width: int, height: int, x: int, y: int, rgb: tuple) -> None:
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 4
        buf[i : i + 4] = bytes((*rgb, 255))


def _disc(buf, width, height, cx: float, cy: float, radius: float, rgb: tuple) -> None:
    span = int(radius)
    icx, icy = int(round(cx)), int(round(cy))
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            if dx * dx + dy * dy <= radius * radius:
                _put(buf, width, height, icx + dx, icy + dy, rgb)


def _line(buf, width, height, x0, y0, x1, y1, radius: float, rgb: tuple) -> None:
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
    for i in range(steps + 1):
        t = i / steps
        _disc(buf, width, height, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, radius, rgb)


def _draw_overlay(buf: bytearray, width: int, height: int, map_data: MapData, scale: int) -> None:
    """Dessine le trajet, la base puis le robot (avec son cap) sur l'image RGBA."""

    def px(x: float, y: float) -> tuple[float, float]:
        cx, cy = to_cell(x, y)
        return cx * scale, cy * scale

    stroke = max(1.0, scale * 0.5)
    for segment in map_data.trail:
        points = [px(x, y) for x, y in segment]
        if len(points) == 1:
            _disc(buf, width, height, *points[0], stroke, TRAIL_RGB)
        for a, b in zip(points, points[1:], strict=False):
            _line(buf, width, height, *a, *b, stroke, TRAIL_RGB)
    if map_data.dock:
        dx, dy = px(*map_data.dock)
        half = max(2, round(2 * scale))
        for yy in range(-half, half + 1):
            for xx in range(-half, half + 1):
                _put(buf, width, height, round(dx) + xx, round(dy) + yy, DOCK_RGB)
    if map_data.robot:
        x, y, angle = map_data.robot
        cx, cy = px(x, y)
        radius = _ROBOT_RADIUS_CELLS * scale
        _disc(buf, width, height, cx, cy, radius + max(1.0, scale * 0.5), _OUTLINE_RGB)
        _disc(buf, width, height, cx, cy, radius, ROBOT_RGB)
        if angle is not None:
            heading = math.radians(angle)
            _line(
                buf, width, height, cx, cy,
                cx + math.cos(heading) * radius, cy - math.sin(heading) * radius,
                max(1.0, scale * 0.4), _OUTLINE_RGB,
            )


def render_png(map_data: MapData, *, scale: int = 1, overlay: bool = False) -> bytes:
    """Rend la carte en PNG RGBA sans dépendance externe (pas de Pillow).

    ``scale`` agrandit l'image d'un facteur entier (1 à 8). ``overlay=True`` superpose le trajet,
    la base et le robot (avec son cap) ; ce qui sort de la grille est ignoré.
    """
    scale = max(1, min(int(scale), _MAX_SCALE))
    width, height = map_data.width * scale, map_data.height * scale
    grid = _scaled_grid(map_data.grid, map_data.width, map_data.height, scale)
    rgba = bytearray(len(grid) * 4)
    for offset, table in enumerate(_TABLES):
        rgba[offset::4] = grid.translate(table)
    if overlay:
        _draw_overlay(rgba, width, height, map_data, scale)
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
