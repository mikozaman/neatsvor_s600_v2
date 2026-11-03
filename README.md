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
- Battery level and vendor online/offline state (when the cloud sends those updates).
- Optional JoyLife account login for REST account data (rooms, maps, voice packs, devices).
- `neatsvor_s600.clean_rooms` service for targeted cleaning. The wire format and
  level ranges remain **experimental and not validated on a physical robot**.
- MQTT reconnect backoff, bounded gzip/protobuf parsing, input validation, and
  non-blocking Home Assistant setup.

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

Run the tests with `python -m unittest discover -s tests` in an environment with Python.
Home Assistant integration tests additionally require Home Assistant's test dependencies.
