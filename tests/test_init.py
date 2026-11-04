"""Tests for integration setup and unload."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from custom_components.neatsvor_s600.api import NeatsvorApiError, NeatsvorAuthError
from custom_components.neatsvor_s600.const import DOMAIN
from custom_components.neatsvor_s600.coordinator import NeatsvorCoordinator
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import MOCK_MAC

ENTITY_ID = "vacuum.neatsvor_s600"


def _entry_without_token() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Neatsvor S600 ({MOCK_MAC})",
        unique_id=MOCK_MAC,
        data={"mac": MOCK_MAC, "email": "user@example.com"},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_runtime_data_and_entity(hass, mock_config_entry, client_cls, api_cls):
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert isinstance(mock_config_entry.runtime_data.coordinator, NeatsvorCoordinator)
    assert mock_config_entry.runtime_data.api is api_cls.return_value
    client_cls.return_value.connect.assert_called_once_with()
    api_cls.return_value.set_token.assert_called_once_with("tok")
    api_cls.return_value.login.assert_not_called()

    entity_id = er.async_get(hass).async_get_entity_id("vacuum", DOMAIN, f"neatsvor_s600_{MOCK_MAC}")
    assert entity_id == ENTITY_ID
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MOCK_MAC)}) is not None


async def test_login_auth_error_starts_reauth(hass, client_cls, api_cls):
    api_cls.return_value.login.side_effect = NeatsvorAuthError("refused")
    entry = _entry_without_token()
    with patch("homeassistant.config_entries.ConfigEntry.async_start_reauth") as start_reauth:
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    start_reauth.assert_called_once()
    assert hass.states.get(ENTITY_ID) is not None


async def test_login_api_error_does_not_start_reauth(hass, client_cls, api_cls):
    api_cls.return_value.login.side_effect = NeatsvorApiError("server down")
    entry = _entry_without_token()
    with patch("homeassistant.config_entries.ConfigEntry.async_start_reauth") as start_reauth:
        await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    start_reauth.assert_not_called()


async def test_successful_login_stores_token(hass, client_cls, api_cls):
    entry = _entry_without_token()
    await _setup(hass, entry)
    assert entry.data["app_token"] == "new-token"


async def test_unload_stops_mqtt(hass, mock_config_entry, client_cls, api_cls):
    await _setup(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    client_cls.return_value.disconnect.assert_called_once_with()


async def test_cloud_unreachable_entity_exists_and_commands_fail(
    hass, mock_config_entry, client_cls, api_cls
):
    client_cls.return_value.is_connected.return_value = False
    await _setup(hass, mock_config_entry)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "docked"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("vacuum", "start", {"entity_id": ENTITY_ID}, blocking=True)
    client_cls.return_value.send_command.assert_not_called()
