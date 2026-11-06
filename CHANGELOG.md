# Changelog

## 0.4.0
- Map: `MAP_<mac>` subscription, protobuf decoder (`map_decoder.py`) and dependency-free PNG renderer,
  exposed as `image.neatsvor_s600_map` (rooms attribute); renders throttled to one per 2 s.
- Battery sensor entity.
- One "Clean <room>" button per room of the map (created automatically).
- `clean_rooms` accepts room names (`rooms`, accents/case ignored, unique partial match) as well as `room_ids`.
- Per-room settings from the map (fan_level, water_level, clean_times) exposed in the map image `room_settings` attribute.
- `clean_rooms`: `fan_level` / `water_level` / `mode` now optional, default `-1` (use map settings,
  identical to the official app frame, 97 raw bytes). Negative int32 values are encoded as 10-byte varints.
- Vacuum entity exposes the room names from the map.
- Docs: `docs/PROTOCOL.md`, `docs/dashboard.yaml`; `tools/mqtt_listen.py`.

## 0.3.0
- Coordinator-based rewrite, `runtime_data`, reauth, diagnostics, translations, tests, CI.
