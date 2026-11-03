# Neatsvor S600 Integration Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `neatsvor_s600` v0.2.0 around a push-only coordinator, with reauth, diagnostics, translations, tests and HACS tooling, without changing observable robot behaviour.

**Architecture:** A `NeatsvorCoordinator` owns the MQTT client and the cleaning/returning inference and pushes `NeatsvorState` to a thin vacuum entity. Clients live in `entry.runtime_data`. `mqtt_client.py`, `protobuf_lite.py` and `api.py` keep their logic and stay free of Home Assistant imports.

**Tech Stack:** Python, Home Assistant custom integration, paho-mqtt 2.x, aiohttp, pytest-homeassistant-custom-component, ruff, GitHub Actions (hassfest, HACS action).

**Spec:** `docs/superpowers/specs/2026-11-03-neatsvor-s600-integration-quality-design.md` (approved 2026-11-03). Executors read both.

## Global Constraints

- Coordinator is push-only: `update_interval=None`.
- Clients are stored in `entry.runtime_data`, typed `NeatsvorConfigEntry`.
- paho reconnect backoff stays 1 to 30 s; MQTT connects asynchronously at setup.
- `mqtt_client.py`, `protobuf_lite.py`, `api.py` have no Home Assistant imports.
- The cloud `online` flag stays an attribute; the entity does not become `unavailable` when the robot is offline.
- Service validation lives only in the voluptuous schema (duplicate checks removed from the entity).
- Translations: `strings.json`, `translations/en.json`, `translations/fr.json`; service and exception texts live there.
- Unique ID `neatsvor_s600_{mac}` and device identifier `(DOMAIN, mac)` are unchanged, so the entity ID survives the upgrade.
- Tests use `pytest-homeassistant-custom-component`; no hardware needed. `clean_rooms` stays labelled unvalidated.
- No `LICENSE` file in this round.
- Plan decisions (not in the spec; owner confirms at review): `hacs.json` floor `homeassistant: 2025.1.0` (first release with `VacuumActivity`); requirement `paho-mqtt>=2.1.0,<3` instead of an exact pin, because Home Assistant core pins paho itself; `integration_type: device`; a command that fails to publish must not change `last_command`.
- Owner-supplied values needed in Task 8: GitHub repo URL and GitHub handle (manifest `documentation`, `issue_tracker`, `codeowners`).
- Working tree: a clone of the owner's GitHub repo on branch `quality-restructure`, created from a commit tagged `v0.2.0` whose contents match the uploaded zip.

## Review Focus

1. Cloud unreachable at startup: the entry still loads, the vacuum entity exists, and a command raises the translated `not_connected` error (Task 4).
2. A publish that fails or times out: the user sees a translated error and the cleaning/returning inference is not flipped (Task 3, Task 4).
3. Partial updates: a STATE message without battery, or an online message without status, keeps the previous values (Task 3).
4. MQTT callback after unload or reload: ignored silently, no exception from the paho thread (Task 3).
5. Home Assistant versions where the vacuum entity no longer reports battery: Task 9 reads the live entity before install and stops to ask the owner if `battery_level` is missing, because a battery sensor would be a spec change.

---

### Task 1: Test tooling and protobuf test fix

**Files:**
- Create: `requirements_test.txt`, `pyproject.toml` (ruff + pytest config), `tests/__init__.py`, `tests/conftest.py`
- Modify: `tests/test_protobuf_lite.py`

**Interfaces:**
- Produces: `conftest.py` with `pytest_plugins = "pytest_homeassistant_custom_component"` and an autouse fixture enabling custom integrations; shared fixture `mock_config_entry() -> MockConfigEntry` with data `{"mac": "12-34-56-78-9A-BC", "email": "user@example.com", "app_token": "tok"}`, domain `neatsvor_s600`.

- [ ] **Step 1: Write the failing tests.** Rewrite the three error tests with real bytes and `assertRaisesRegex`: `b"\x80"` -> "Truncated protobuf varint"; `b"\x0a\x05x"` -> "Truncated length-delimited"; `b"\x00"` -> "Invalid protobuf field number 0". Add `test_rejects_unsupported_wire_type` (`b"\x0b"` -> "Unsupported protobuf wire type: 3") and `test_rejects_overlong_varint` (`b"\x80" * 10 + b"\x01"` -> "exceeds 10 bytes").
- [ ] **Step 2: Run** `pytest tests/test_protobuf_lite.py -v`. Expected: the new assertions pass against the existing codec (the codec is correct; the old tests were not exercising it). If any fails, the codec has a bug: stop and report.
- [ ] **Step 3: Add** `requirements_test.txt` (`pytest-homeassistant-custom-component` pinned exactly to the latest release at execution time, plus `ruff`) and `pyproject.toml` ruff config targeting `custom_components` and `tests`. Install and run `ruff check .`; fix findings.
- [ ] **Step 4: Run** `pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** `test: real-byte protobuf tests, test tooling`.

### Task 2: MQTT client hooks and frame tests

**Files:**
- Modify: `custom_components/neatsvor_s600/mqtt_client.py`
- Test: `tests/test_mqtt_client.py`

**Interfaces:**
- Produces: `NeatsvorMqttClient.__init__(self, mac: str, on_update: Callable[[dict[str, Any]], None], on_connection: Callable[[bool], None] | None = None)`; `is_connected(self) -> bool`. `on_connection(True)` fires on a successful connect, `on_connection(False)` on disconnect or refused connect. Existing `connect`, `disconnect`, `send_command(command_code: int)`, `send_room_clean(room_ids, fan_level, water_level, mode=1)` unchanged.

- [ ] **Step 1: Write failing tests**, patching `paho.mqtt.client.Client` with a mock whose `publish` returns a result with `rc=0` and `is_published() -> True`:
  - `test_parse_state_message`: gzip of `length_delimited_field(2, varint_field(1, 2) + varint_field(2, 87))` on topic `STATE_<mac>` calls `on_update({"status_code": 2, "battery": 87})`; a body without field 1 gives `status_code: None`.
  - `test_parse_online_message`: body field 1 equal to 2 gives `{"online": True}`; equal to 1 gives `False`.
  - `test_rejects_bad_payloads`: non-gzip bytes, payload above 256_000 bytes, gzip expanding past 1_000_000 bytes, and gzip followed by trailing bytes each leave `on_update` uncalled and raise nothing.
  - `test_start_frame`: decompress the published payload, decode with `protobuf_lite`; header has version 1, loginName `b"00000033314"`, packed cmdId `[1]`, cmdType 1; body type_url `type.googleapis.com/bvsdk.MqttMsgBody`, value `b"\x08\x02"`. Stop uses cmdId 2. Compare after decompressing (gzip headers carry a timestamp).
  - `test_room_clean_frame`: cmdId 31, type_url `type.googleapis.com/sweeper.Rooms`, value `b"\x0a\x02\x01\x02\x10\x02\x18\x02\x20\x01"` for rooms `[1, 2]`, fan 2, water 2, mode 1.
  - `test_publish_failure_raises`: `rc != 0` raises `ConnectionError`; `is_published() -> False` raises `TimeoutError`.
  - `test_connection_callbacks`: invoking the paho `on_connect` with reason code 0 calls `on_connection(True)` and subscribes to `STATE_<mac>` and `DEVICE_ON_LINE_<mac>`; `on_disconnect` calls `on_connection(False)`.
- [ ] **Step 2: Run** `pytest tests/test_mqtt_client.py -v`. Expected: the callback and `is_connected` tests FAIL; parsing and frame tests pass.
- [ ] **Step 3: Implement** the `on_connection` parameter and `is_connected()` (delegates to the paho client) in `mqtt_client.py`. Keep the file free of Home Assistant imports.
- [ ] **Step 4: Run** `pytest tests/test_mqtt_client.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: connection callbacks on MQTT client, frame tests`.

### Task 3: Coordinator and state logic

**Files:**
- Create: `custom_components/neatsvor_s600/coordinator.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: Task 2's `NeatsvorMqttClient` signature.
- Produces (all in `coordinator.py`):
  - `@dataclass(frozen=True) class NeatsvorState: activity: VacuumActivity = VacuumActivity.DOCKED; battery: int | None = None; online: bool | None = None; last_command: int = COMMAND_STOP_RETURN; connected: bool = False`
  - `apply_update(state: NeatsvorState, parsed: dict[str, Any]) -> NeatsvorState` (pure; same rules as today's `_handle_update`: `status_code` None means paused, 1 docked, other values cleaning if `last_command == COMMAND_START_RESUME` else returning; `battery` and `online` change only when present and not None).
  - `@dataclass class NeatsvorData: coordinator: NeatsvorCoordinator; api: NeatsvorApiClient` and `type NeatsvorConfigEntry = ConfigEntry[NeatsvorData]`.
  - `class NeatsvorCoordinator(DataUpdateCoordinator[NeatsvorState])` with `__init__(self, hass, entry: NeatsvorConfigEntry)` (`update_interval=None`, initial data `NeatsvorState()`), `async_connect(self) -> None`, `async_shutdown(self) -> None`, `async_start(self) -> None`, `async_stop(self) -> None`, `async_return_home(self) -> None`, `async_clean_rooms(self, room_ids: list[int], fan_level: int, water_level: int, mode: int = 1) -> None`.

- [ ] **Step 1: Write failing tests** for `apply_update`: missing status gives PAUSED; status 1 gives DOCKED; status 2 with last command start gives CLEANING; status 2 with last command stop gives RETURNING; battery None keeps the previous battery; a message with only `online` keeps the previous activity. Coordinator tests with `NeatsvorMqttClient` patched in the `coordinator` module: `async_start` publishes command 1 and sets `last_command` only after the publish succeeds; a publish raising `TimeoutError` raises `HomeAssistantError` (translation key `command_failed`) and leaves `last_command` unchanged; disconnected client raises `HomeAssistantError` (key `not_connected`); `async_clean_rooms` forwards its arguments; connection loss logs one warning per outage and one info on recovery (use `caplog`); after `async_shutdown`, invoking the client's `on_update` callback raises nothing and changes no data.
- [ ] **Step 2: Run** `pytest tests/test_coordinator.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `coordinator.py`. Marshal paho-thread callbacks with `hass.loop.call_soon_threadsafe`, then `async_set_updated_data`; drop callbacks once shut down. Run blocking `connect`, `disconnect` and publishes via `hass.async_add_executor_job`. Connect uses `connect_async` as today.
- [ ] **Step 4: Run** `pytest tests/test_coordinator.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: push coordinator owning MQTT and state logic`.

### Task 4: Entity, setup and unload

**Files:**
- Create: `custom_components/neatsvor_s600/entity.py`
- Modify: `custom_components/neatsvor_s600/__init__.py`, `custom_components/neatsvor_s600/vacuum.py`
- Test: `tests/test_init.py`, `tests/test_vacuum.py`

**Interfaces:**
- Consumes: Task 3's `NeatsvorCoordinator`, `NeatsvorData`, `NeatsvorConfigEntry`.
- Produces: `class NeatsvorEntity(CoordinatorEntity[NeatsvorCoordinator])` setting `_attr_has_entity_name = True` and the existing `DeviceInfo`; `NeatsvorVacuum(NeatsvorEntity, StateVacuumEntity)` with `activity`, `battery_level` and `extra_state_attributes` (`{"online": ...}`) read from `coordinator.data`; `async_setup_entry(hass, entry: NeatsvorConfigEntry) -> bool` and `async_unload_entry(hass, entry: NeatsvorConfigEntry) -> bool` in `__init__.py`.

- [ ] **Step 1: Write failing tests** (patching the MQTT client and the REST client):
  - setup stores `NeatsvorData` in `entry.runtime_data`; the vacuum entity exists with unique ID `neatsvor_s600_12-34-56-78-9A-BC` and device identifier `(neatsvor_s600, 12-34-56-78-9A-BC)`.
  - REST login raising `NeatsvorAuthError` with no stored token: setup still succeeds and a reauth flow is started (`entry.async_start_reauth`); `NeatsvorApiError` at login: setup succeeds, no reauth.
  - a stored token skips login; a successful login writes `app_token` into the entry data.
  - unload calls the coordinator's `async_shutdown` once and returns True.
  - cloud unreachable (client `is_connected() -> False`): the vacuum entity still exists in state DOCKED and `vacuum.start` raises `HomeAssistantError`.
  - state pushed through the coordinator updates `activity`, `battery_level` and the `online` attribute; `online: False` leaves the entity available.
  - `start`, `stop` and `return_to_base` call the matching coordinator methods; `neatsvor_s600.clean_rooms` with valid data reaches `async_clean_rooms`; room IDs `[0]`, fan level 4 and an empty room list are rejected by the schema.
- [ ] **Step 2: Run** `pytest tests/test_init.py tests/test_vacuum.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Move `hass.data` usage out; build `NeatsvorApiClient`, run the existing best-effort REST login (same logging), create the coordinator, `await coordinator.async_connect()`, forward the `vacuum` platform. In `vacuum.py` keep the schema from v0.2.0 verbatim and delete the duplicate range checks in the entity method. Keep `VacuumEntityFeature.START | STOP | RETURN_HOME | STATE`.
- [ ] **Step 4: Run** `pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor: runtime_data, thin vacuum entity, reauth trigger`.

### Task 5: Config flow, reauth and translations

**Files:**
- Modify: `custom_components/neatsvor_s600/config_flow.py`, `strings.json`, `services.yaml`
- Create: `custom_components/neatsvor_s600/translations/en.json`, `translations/fr.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `NeatsvorApiClient.login(email: str) -> str`.
- Produces: `async_step_reauth(entry_data: Mapping[str, Any])`, `async_step_reauth_confirm(user_input)`; translation keys `config.step.user`, `config.step.account`, `config.step.reauth_confirm`, `config.error.{invalid_mac,invalid_auth,cannot_connect,invalid_email}`, `config.abort.{already_configured,reauth_successful}`, `exceptions.{not_connected,command_failed}.message`, `services.clean_rooms` (name, description, field names).

- [ ] **Step 1: Write failing tests:** MAC `12:34:56:78:9a:bc` (lowercase, colons, surrounding spaces) is stored as `12-34-56-78-9A-BC`; `123456789ABC` and `12-34` give `invalid_mac`; a second entry for the same MAC aborts `already_configured`; account step errors for malformed email (`invalid_email`), `NeatsvorAuthError` (`invalid_auth`), `NeatsvorApiError` (`cannot_connect`); success creates an entry titled `Neatsvor S600 (12-34-56-78-9A-BC)` with `mac`, `email`, `app_token`; reauth with a valid email updates `app_token` and `email`, reloads the entry and aborts `reauth_successful`; reauth with a refused email shows `invalid_auth`.
- [ ] **Step 2: Run** `pytest tests/test_config_flow.py -v`. Expected: reauth tests FAIL, the rest pass.
- [ ] **Step 3: Implement** the reauth steps (use `self._get_reauth_entry()` and `async_update_reload_and_abort`). Correct `invalid_auth` text so it no longer mentions a password. Add a test that fails if `strings.json`, `en.json` and `fr.json` have different key sets.
- [ ] **Step 4: Run** `pytest -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: reauth flow and translations`.

### Task 6: Diagnostics

**Files:**
- Create: `custom_components/neatsvor_s600/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `NeatsvorConfigEntry`, `NeatsvorState`.
- Produces: `async_get_config_entry_diagnostics(hass, entry: NeatsvorConfigEntry) -> dict[str, Any]` returning `{"entry": <redacted data>, "state": {"activity", "battery", "online", "connected"}}`; keys `mac`, `email`, `app_token` redacted with `async_redact_data`.

- [ ] **Step 1: Write failing test:** the result contains the state fields and none of the MAC, email or token strings appear anywhere in `json.dumps(result)`.
- [ ] **Step 2: Run** `pytest tests/test_diagnostics.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `diagnostics.py`.
- [ ] **Step 4: Run** `pytest tests/test_diagnostics.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: diagnostics with redaction`.

### Task 7: REST client tests

**Files:**
- Test: `tests/test_api.py` (no source change expected)

**Interfaces:**
- Consumes: `NeatsvorApiClient(session)`, `NeatsvorApiError`, `NeatsvorAuthError`.

- [ ] **Step 1: Write tests** with `aioclient_mock` against `https://de.wisdom.blackvision.net`: login success stores token, `user_id`, `account_id`, `home_id`; response without token raises `NeatsvorAuthError`; body code `10200` raises `NeatsvorAuthError`; other non-success code, HTTP 500, non-JSON body and a JSON list body raise `NeatsvorApiError`; timeout raises `NeatsvorApiError`; authenticated call without a token raises `NeatsvorAuthError`; `get_rooms` accepts both a bare list and `{"list": [...]}`.
- [ ] **Step 2: Run** `pytest tests/test_api.py -v`. Expected: PASS. A failure means a real bug in `api.py`: fix it minimally and note it in the commit message.
- [ ] **Step 3: Commit** `test: REST client`.

### Task 8: Packaging, docs and CI

**Files:**
- Modify: `custom_components/neatsvor_s600/manifest.json`, `hacs.json`, `README.md`, `CONTRIBUTING.md`
- Create: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: owner-supplied repo URL and GitHub handle (ask the owner first; do not invent them).

- [ ] **Step 1: Update the manifest:** add `integration_type: device`, `documentation`, `issue_tracker`, `codeowners`; requirement `paho-mqtt>=2.1.0,<3`; keys sorted as hassfest expects (`domain`, `name`, then alphabetical); bump `version` to `0.3.0`.
- [ ] **Step 2: Complete `hacs.json`** (`name`, `homeassistant: 2025.1.0`).
- [ ] **Step 3: Write `CONTRIBUTING.md`** (setup, `pytest`, `ruff check .`, branch and PR flow) in under 40 lines; update the README development section and add reauth and diagnostics notes.
- [ ] **Step 4: Add the workflow** with four jobs: `hassfest` (`home-assistant/actions/hassfest`), HACS validation (`hacs/action`, category `integration`), `ruff check`, `pytest`.
- [ ] **Step 5: Run** `ruff check .` and `pytest -v` locally. Expected: clean and PASS. Push the branch and confirm all four CI jobs are green.
- [ ] **Step 6: Commit** `chore: manifest, hacs.json, docs, CI`.

### Task 9: Install and smoke test on the owner's Home Assistant

**Files:** none (verification only).

**Interfaces:**
- Consumes: ha-mcp tools `ha_get_state` (read), `ha_manage_hacs` (write), `ha_get_hacs_info` (read); the pushed branch from Task 8.

- [ ] **Step 1: Baseline (before any install).** With ha-mcp, read the current vacuum entity's state and attributes and record them. If `battery_level` is absent, stop and ask the owner (Review Focus 5).
- [ ] **Step 2: Offer a Home Assistant backup;** make one only if the owner says yes.
- [ ] **Step 3: Install.** `ha_manage_hacs` `add_repository` (owner's repo URL, category `integration`), then `download` of branch `quality-restructure`. Owner restarts Home Assistant.
- [ ] **Step 4: Verify with ha-mcp.** The integration loads without repairs or log errors; the vacuum entity ID, state and attributes match the baseline; the entity is not duplicated.
- [ ] **Step 5: Owner checks by hand:** start, stop and return-to-base on the robot; a diagnostics download shows no MAC, email or token.
- [ ] **Step 6: Rollback path, if anything regresses:** `download` tag `v0.2.0` through HACS and restart (or restore the backup if one was made).
