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
- Battery level is tracked internally and shown in the diagnostics download, but there is
  **no battery entity yet**: Home Assistant deprecated battery attributes on vacuum entities,
  and a proper battery sensor has not been added.
- Re-authentication flow if the JoyLife account is refused, and a diagnostics download with
  the MAC address, email and token redacted.
- English and French translations.
- Optional JoyLife account login for REST account data (rooms, maps, voice packs, devices).
- `neatsvor_s600.clean_rooms` service for targeted cleaning. The wire format and
  level ranges remain **experimental and not validated on a physical robot**.
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

## Service: `neatsvor_s600.clean_rooms`

Example:

```yaml
action: neatsvor_s600.clean_rooms
target:
  entity_id: vacuum.neatsvor_s600
data:
  room_ids: [1, 2]
  fan_level: 2
  water_level: 2
  mode: 1
```

Room IDs must be positive integers. Fan and water levels are currently restricted to
1–3 and mode to 1–5. These values and the room command have not been validated against
a physical S600; use at your own risk and do not assume these ranges match every firmware.

## Security and limitations

- MQTT is cloud-based and the current endpoint/port is not known to support TLS.
- Vendor app credentials embedded in the upstream mobile app are not private user
  credentials; rotating or removing them requires a supported vendor authentication flow.
- Do not share diagnostic logs containing MAC addresses, account identifiers, or tokens.
- The reverse-engineered protobuf schema may change with vendor firmware updates.
- No live robot was available in this development environment. Start/stop, status
  interpretation, and room cleaning still require hardware validation.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `pip install -r requirements_test.txt`,
then `ruff check .` and `pytest`. The suite needs no robot and no network.

Requires Home Assistant 2025.1.0 or newer.
