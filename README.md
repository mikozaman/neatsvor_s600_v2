# Neatsvor S600 for Home Assistant

Unofficial Home Assistant custom integration for the Neatsvor S600 / JoyLife platform.

> **Important security note:** the vendor MQTT endpoint used by this integration is
> `de.mqtt.blackvision.net:8011`. The available protocol details indicate that this
> endpoint does not use TLS. MQTT credentials and the app identity values are vendor
> application constants, not per-user secrets. This integration cannot make that
> cloud connection confidential or authenticate the robot independently. Use it only
> if you accept that limitation; do not expose MQTT credentials or packet captures.
> A TLS endpoint has deliberately not been guessed. REST requests use HTTPS.

## Current functionality

- Vacuum entity with start/resume, stop, and return-to-base commands.
- Vendor online/offline state as an `online` attribute of the vacuum entity. The entity
  stays available when the robot is reported offline.
- **Battery sensor** (`sensor.neatsvor_s600_battery`).
- **Map image** (`image.neatsvor_s600_map`): the map published by the robot on its `MAP_<mac>` topic is
  decoded and rendered as a PNG (rooms coloured, walls dark); room names are exposed in the `rooms`
  attribute (also on the vacuum entity). The robot (with its heading), its cleaning path and the
  dock are drawn on the map, which is enlarged 3x. Forbidden zones and virtual walls are not
  drawn yet, and the rendering has not been checked on a live Home Assistant instance.
- Re-authentication flow if the JoyLife account is refused, and a diagnostics download with
  the MAC address, email and token redacted.
- English and French translations.
- Optional JoyLife account login for REST account data (rooms, maps, voice packs, devices).
- `neatsvor_s600.clean_rooms` service for targeted cleaning, **validated on a physical S600**
  when called with `room_ids` only (the robot then applies the suction/mopping levels saved on the
  map for each room, exactly like the official app).
- MQTT reconnect backoff, bounded gzip/protobuf parsing, input validation, and
  non-blocking Home Assistant setup. A command sent while the cloud connection is down
  fails with a clear error instead of being silently lost.

## Installation

### HACS
1. In HACS, open **Integrations**.
2. Add this repository as a custom repository, category **Integration**.
3. Download **Neatsvor S600** and restart Home Assistant.
4. Add the integration from **Settings → Devices & services**.

### Manual
Copy `custom_components/neatsvor_s600` into
`<config>/custom_components/neatsvor_s600`, then restart Home Assistant.

## Configuration

1. Enter the robot's MAC address. Colons and hyphens are accepted.
2. Enter the JoyLife account email used by the vendor app. The current setup flow
   requires this email to complete the vendor SDK login; it does not ask for the
   account password. The REST account endpoints are groundwork for further features
   and are not yet exposed as Home Assistant entities.

The robot and Home Assistant must both have internet access to reach the vendor cloud.
Despite the historical “Local” name, this is **not local-only control**.

## Cleaning specific rooms

**One button per room** — once the robot has published its map, a `button.neatsvor_s600_clean_<room>`
entity appears for every room ("Clean Kitchen"…). Pressing it cleans that room with the suction/mopping
settings saved on the map.

**Service `neatsvor_s600.clean_rooms`** — a list of rooms, by name and/or id:

```yaml
action: neatsvor_s600.clean_rooms
target:
  entity_id: vacuum.neatsvor_s600
data:
  rooms: [Cuisine, Séjour]      # names (case/accents ignored, unique partial name works) or ids
  # room_ids: [1, 2]            # alternative / addition
```

Unknown or ambiguous names are rejected with the list of available rooms. `fan_level`, `water_level`
and `mode` are optional and default to `-1` ("use the setting saved on the map"), the validated
behaviour; explicit values did not change the robot's behaviour in tests (accepted: `-1` or 1–4 for
levels, 1–5 for mode). The rooms and their per-room settings are listed in the attributes of the map
image. Dashboard example: [`docs/dashboard.yaml`](docs/dashboard.yaml).

## Security and limitations

- MQTT is cloud-based and the current endpoint/port is not known to support TLS.
- Vendor app credentials embedded in the upstream mobile app are not private user
  credentials; rotating or removing them requires a supported vendor authentication flow.
- Do not share diagnostic logs containing MAC addresses, account identifiers, or tokens.
- The reverse-engineered protobuf schema may change with vendor firmware updates.
- Start/stop, status interpretation and room cleaning were validated on a real S600 by the author;
  the battery sensor and map image were added afterwards and still need confirmation on a live instance.
- Protocol notes and open questions: [`docs/PROTOCOL.md`](docs/PROTOCOL.md). `tools/mqtt_listen.py`
  records raw frames to continue the reverse engineering.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `pip install -r requirements_test.txt`,
then `ruff check .` and `pytest`. The suite needs no robot and no network.

Requires Home Assistant 2025.1.0 or newer.
