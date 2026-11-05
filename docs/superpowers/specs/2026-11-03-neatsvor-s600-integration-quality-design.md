# Neatsvor S600 integration: quality restructure (design)

Date: 2026-11-03
Baseline: `neatsvor_s600` v0.2.0 (zip `ha-neatsvor-s600-v0_2_0`)
Status: draft, awaiting review

## 1. Purpose

Bring the integration up to the standard Home Assistant structure and tooling
so it is maintainable now and can be published on HACS later without another
restructure.

**Stated by the owner**
- Priority is integration quality (coordinator, `runtime_data`, translations,
  reauth, diagnostics, tests), not new features.
- Usage is private for now; a public HACS release is possible later.
- The coordinator-centred approach (option 1) is chosen; no separate PyPI
  library for now.

**Assumptions (to be confirmed at review)**
- Existing behaviour must not regress: start, stop, return-to-base,
  `clean_rooms`, battery and online state.
- Entities stay as they are (one vacuum entity). No new platforms this round.
- The cloud `online` flag stays an attribute; the entity does not become
  `unavailable` when the robot is offline.

## 2. Success criteria

- `hassfest` and the HACS validation action pass.
- Tests cover coordinator state logic, MQTT parsing and frame encoding, config
  flow (including reauth), setup/unload, services, diagnostics and the REST
  client.
- No change in observable behaviour except clearer error messages and the new
  reauth and diagnostics features.

## 3. Non-goals

- New sensors, selects, room names, maps or fan/water entities.
- Validating `clean_rooms` on hardware (stays labelled unvalidated).
- TLS for the vendor MQTT endpoint, replacing the shared vendor credentials, or
  a `LICENSE` file. These are recorded in section 8 as prerequisites for going
  public.
- Extracting the protocol code into a PyPI library.

## 4. Architecture

Data flow: robot -> vendor cloud -> paho thread -> coordinator -> entity state.

| Module | Responsibility |
|---|---|
| `coordinator.py` (new) | `NeatsvorCoordinator`, push-only (`update_interval=None`). Owns the MQTT client. Holds `NeatsvorState` (activity, battery, online, last command). Receives paho callbacks and hands them to the event loop with `call_soon_threadsafe`, then `async_set_updated_data`. Contains the cleaning-vs-returning inference (moved from the entity). Exposes `async_start`, `async_stop`, `async_return_home`, `async_clean_rooms`; blocking publishes run in the executor. |
| `entity.py` (new) | `NeatsvorEntity(CoordinatorEntity)` base: shared `DeviceInfo` and unique-ID pattern. |
| `vacuum.py` | Thin entity: reads coordinator state, forwards commands, registers the `clean_rooms` service. |
| `__init__.py` | Builds REST client and coordinator, stores them in `entry.runtime_data` (typed `NeatsvorConfigEntry`), starts MQTT, stops it on unload. REST login stays best-effort. |
| `config_flow.py` | Existing two steps plus a reauth step; corrected error strings. |
| `mqtt_client.py`, `protobuf_lite.py`, `api.py` | Logic unchanged; no Home Assistant imports, so extraction into a library stays cheap. |

## 5. Behaviour

**MQTT lifecycle**
- Async connect at setup; paho reconnect backoff stays 1 to 30 s.
- The coordinator tracks connected/disconnected and logs once per outage and
  once on recovery.
- A command sent while disconnected or unacknowledged raises a translated
  `HomeAssistantError`.
- Corrupt payloads are still caught and logged in `mqtt_client.py`.

**Services**: validation lives only in the voluptuous schema; the duplicate
checks in `async_clean_rooms` are removed.

**REST and reauth**: if login is refused at setup, the integration still loads,
MQTT control works, and a reauth flow starts. The reauth step asks for the
email, logs in again and updates the stored token. Setup never fails because of
REST.

**Config flow**: MAC accepts colons or hyphens; error strings corrected (no
mention of a password).

**Diagnostics**: coordinator state, connection status and entry data, with MAC,
email and token redacted.

**Translations**: `strings.json`, `translations/en.json`, `translations/fr.json`;
service and exception texts move into them.

## 6. Testing

Tooling: `pytest-homeassistant-custom-component`. No hardware required.

- Coordinator: missing status field -> paused; status 1 -> docked; status 2 ->
  cleaning or returning depending on the last command.
- MQTT client: state and online parsing; rejection of oversized, truncated and
  corrupt payloads; outgoing frames for start, stop and `clean_rooms` compared
  with fixed expected bytes.
- Config flow: invalid MAC, duplicate robot, each account-step error, reauth.
- Setup/unload: REST login failure does not block setup; MQTT stops cleanly.
- Entity and service: commands reach the coordinator; disconnected robot raises
  the translated error; diagnostics redaction.
- REST client: `aioclient_mock`.
- Existing `tests/test_protobuf_lite.py` is fixed: it uses `b"\\x80"`-style
  literals (a backslash followed by text) instead of real bytes, so the
  truncation tests currently pass through an unsupported-wire-type error. They
  are rewritten with real bytes so they exercise the error they name.

## 7. Packaging and tooling

- Manifest: add `integration_type`, `documentation`, `issue_tracker`,
  `codeowners`; pin requirements.
- Complete `hacs.json`.
- Fill in the empty `CONTRIBUTING.md` briefly.
- Add ruff configuration and a test requirements file.
- GitHub Actions: `hassfest`, HACS validation, ruff, pytest.

## 8. Before a public release (out of scope now)

- Add a `LICENSE` file.
- Decide how to handle the shared vendor MQTT credentials and app key/secret
  that are embedded in the source.
- The MQTT endpoint is unencrypted; confirm whether a TLS endpoint exists.
- Validate `clean_rooms` ranges and `mode` meaning on a real robot.

## 9. Risks

- The coordinator move touches the state logic that infers cleaning vs
  returning; the test suite in section 6 exists to guard it.
- Behaviour on a real robot cannot be verified here; the owner should run a
  manual start/stop/return check after the restructure.
