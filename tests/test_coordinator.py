"""Tests for the Neatsvor coordinator and its state logic."""
from __future__ import annotations

import logging

import pytest
from custom_components.neatsvor_s600.const import COMMAND_START_RESUME, COMMAND_STOP_RETURN
from custom_components.neatsvor_s600.coordinator import (
    NeatsvorCoordinator,
    NeatsvorState,
    apply_update,
)
from homeassistant.components.vacuum import VacuumActivity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

LOGGER_NAME = "custom_components.neatsvor_s600.coordinator"


@pytest.mark.parametrize(
    ("last_command", "parsed", "expected"),
    [
        (COMMAND_STOP_RETURN, {"status_code": None, "battery": 50}, VacuumActivity.PAUSED),
        (COMMAND_START_RESUME, {"status_code": 1, "battery": 50}, VacuumActivity.DOCKED),
        (COMMAND_START_RESUME, {"status_code": 2, "battery": 50}, VacuumActivity.CLEANING),
        (COMMAND_STOP_RETURN, {"status_code": 2, "battery": 50}, VacuumActivity.RETURNING),
    ],
    ids=["missing-status-paused", "idle-docked", "active-after-start", "active-after-stop"],
)
def test_apply_update_activity(last_command, parsed, expected):
    state = NeatsvorState(last_command=last_command)
    assert apply_update(state, parsed).activity == expected


def test_apply_update_keeps_battery_when_absent():
    state = NeatsvorState(battery=80, activity=VacuumActivity.CLEANING)
    new = apply_update(state, {"status_code": 2, "battery": None})
    assert new.battery == 80


def test_apply_update_online_only_keeps_activity():
    state = NeatsvorState(activity=VacuumActivity.CLEANING, battery=40, online=True)
    new = apply_update(state, {"online": False})
    assert (new.activity, new.battery, new.online) == (VacuumActivity.CLEANING, 40, False)


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_config_entry, client_cls) -> NeatsvorCoordinator:
    mock_config_entry.add_to_hass(hass)
    return NeatsvorCoordinator(hass, mock_config_entry)


def _callbacks(client_cls):
    args = client_cls.call_args.args
    return args[1], args[2]  # on_update, on_connection


async def test_initial_state(coordinator):
    assert coordinator.update_interval is None
    assert coordinator.data == NeatsvorState()


async def test_push_update_changes_data(hass, coordinator, client_cls):
    on_update, _ = _callbacks(client_cls)
    on_update({"status_code": 1, "battery": 77})
    await hass.async_block_till_done()
    assert coordinator.data.activity == VacuumActivity.DOCKED
    assert coordinator.data.battery == 77


async def test_start_sets_last_command_after_success(coordinator, client_cls):
    await coordinator.async_start()
    client_cls.return_value.send_command.assert_called_once_with(COMMAND_START_RESUME)
    assert coordinator.data.last_command == COMMAND_START_RESUME


async def test_stop_and_return_home_send_stop(coordinator, client_cls):
    await coordinator.async_start()
    await coordinator.async_stop()
    await coordinator.async_return_home()
    calls = client_cls.return_value.send_command.call_args_list
    assert [c.args[0] for c in calls] == [1, 2, 2]
    assert coordinator.data.last_command == COMMAND_STOP_RETURN


async def test_failed_publish_keeps_last_command(coordinator, client_cls):
    client_cls.return_value.send_command.side_effect = TimeoutError("no ack")
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_start()
    assert err.value.translation_key == "command_failed"
    assert coordinator.data.last_command == COMMAND_STOP_RETURN


async def test_not_connected_raises_translated_error(coordinator, client_cls):
    client_cls.return_value.is_connected.return_value = False
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_start()
    assert err.value.translation_key == "not_connected"
    client_cls.return_value.send_command.assert_not_called()


async def test_clean_rooms_forwards_arguments(coordinator, client_cls):
    await coordinator.async_clean_rooms([1, 2], 2, 3, 1)
    client_cls.return_value.send_room_clean.assert_called_once_with([1, 2], 2, 3, 1)
    assert coordinator.data.last_command == COMMAND_START_RESUME


async def test_connection_logged_once_per_outage(hass, coordinator, client_cls, caplog):
    _, on_connection = _callbacks(client_cls)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    for connected in (False, False, True, False):
        on_connection(connected)
        await hass.async_block_till_done()
    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert [r.levelno for r in records] == [logging.WARNING, logging.INFO, logging.WARNING]
    assert coordinator.data.connected is False


async def test_connection_flag_follows_callbacks(hass, coordinator, client_cls):
    _, on_connection = _callbacks(client_cls)
    on_connection(True)
    await hass.async_block_till_done()
    assert coordinator.data.connected is True


async def test_connect_failure_is_logged_not_raised(coordinator, client_cls):
    client_cls.return_value.connect.side_effect = RuntimeError("boom")
    await coordinator.async_connect()
    client_cls.return_value.connect.assert_called_once_with()


async def test_shutdown_disconnects_and_ignores_late_callbacks(hass, coordinator, client_cls):
    on_update, on_connection = _callbacks(client_cls)
    await coordinator.async_connect()
    await coordinator.async_shutdown()
    client_cls.return_value.disconnect.assert_called_once_with()
    on_update({"status_code": 2, "battery": 5})
    on_connection(True)
    await hass.async_block_till_done()
    assert coordinator.data == NeatsvorState()


async def test_shutdown_survives_disconnect_error(coordinator, client_cls):
    client_cls.return_value.disconnect.side_effect = RuntimeError("boom")
    await coordinator.async_shutdown()
    client_cls.return_value.disconnect.assert_called_once_with()
