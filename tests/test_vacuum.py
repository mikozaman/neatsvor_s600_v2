"""Tests for the vacuum entity and the clean_rooms service."""
from __future__ import annotations

import pytest
import voluptuous as vol
from custom_components.neatsvor_s600.const import DOMAIN
from homeassistant.core import HomeAssistant

ENTITY_ID = "vacuum.neatsvor_s600"


@pytest.fixture
async def setup_entry(hass: HomeAssistant, mock_config_entry, client_cls, api_cls):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def _push(client_cls, update: dict) -> None:
    client_cls.call_args.args[1](update)


async def test_state_pushed_through_coordinator(hass, setup_entry, client_cls):
    _push(client_cls, {"status_code": 2, "battery": 63})
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == "returning"
    assert state.attributes["online"] is None


async def test_offline_robot_does_not_make_entity_unavailable(hass, setup_entry, client_cls):
    _push(client_cls, {"online": False})
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state != "unavailable"
    assert state.attributes["online"] is False


@pytest.mark.parametrize(
    ("service", "expected_code"),
    [("start", 1), ("stop", 2), ("return_to_base", 2)],
)
async def test_basic_commands(hass, setup_entry, client_cls, service, expected_code):
    await hass.services.async_call("vacuum", service, {"entity_id": ENTITY_ID}, blocking=True)
    client_cls.return_value.send_command.assert_called_once_with(expected_code)


async def test_start_then_active_status_is_cleaning(hass, setup_entry, client_cls):
    await hass.services.async_call("vacuum", "start", {"entity_id": ENTITY_ID}, blocking=True)
    _push(client_cls, {"status_code": 2, "battery": 50})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == "cleaning"


async def test_clean_rooms_service(hass, setup_entry, client_cls):
    await hass.services.async_call(
        DOMAIN,
        "clean_rooms",
        {"entity_id": ENTITY_ID, "room_ids": [1, 2], "fan_level": 2, "water_level": 3},
        blocking=True,
    )
    client_cls.return_value.send_room_clean.assert_called_once_with([1, 2], 2, 3, 1)


@pytest.mark.parametrize(
    "data",
    [
        {"room_ids": [0], "fan_level": 2, "water_level": 2},
        {"room_ids": [], "fan_level": 2, "water_level": 2},
        {"room_ids": [1], "fan_level": 4, "water_level": 2},
        {"room_ids": [1], "fan_level": 2, "water_level": 0},
        {"room_ids": [1], "fan_level": 2, "water_level": 2, "mode": 6},
    ],
    ids=["room-zero", "no-rooms", "fan-too-high", "water-zero", "mode-too-high"],
)
async def test_clean_rooms_schema_rejects_bad_input(hass, setup_entry, client_cls, data):
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "clean_rooms", {"entity_id": ENTITY_ID, **data}, blocking=True
        )
    client_cls.return_value.send_room_clean.assert_not_called()
