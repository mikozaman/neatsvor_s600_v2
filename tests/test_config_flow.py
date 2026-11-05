"""Tests for the config flow, including reauth."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.neatsvor_s600.api import NeatsvorApiError, NeatsvorAuthError
from custom_components.neatsvor_s600.const import DOMAIN
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MOCK_MAC


@pytest.fixture
def flow_api_cls():
    """Patch the REST client used inside the config flow."""
    with patch("custom_components.neatsvor_s600.config_flow.NeatsvorApiClient") as cls:
        cls.return_value.login = AsyncMock(return_value="flow-token")
        yield cls


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _to_account_step(hass: HomeAssistant, mac: str = MOCK_MAC):
    result = await _start(hass)
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"mac": mac})


@pytest.mark.parametrize(
    "typed", ["12:34:56:78:9a:bc", "  12-34-56-78-9a-bc ", "12-34-56-78-9A-BC"]
)
async def test_mac_is_normalised(hass, flow_api_cls, typed):
    result = await _to_account_step(hass, typed)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "account"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "User@Example.com"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Neatsvor S600 ({MOCK_MAC})"
    assert result["data"] == {"mac": MOCK_MAC, "email": "user@example.com", "app_token": "flow-token"}


@pytest.mark.parametrize("typed", ["123456789ABC", "12-34", "ZZ-34-56-78-9A-BC"])
async def test_invalid_mac(hass, typed):
    result = await _to_account_step(hass, typed)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"mac": "invalid_mac"}


async def test_duplicate_robot_aborts(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await _to_account_step(hass, "12:34:56:78:9a:bc")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("email", "login_error", "expected"),
    [
        ("not-an-email", None, "invalid_email"),
        ("user@example.com", NeatsvorAuthError("refused"), "invalid_auth"),
        ("user@example.com", NeatsvorApiError("down"), "cannot_connect"),
    ],
)
async def test_account_step_errors(hass, flow_api_cls, email, login_error, expected):
    flow_api_cls.return_value.login.side_effect = login_error
    result = await _to_account_step(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": email})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "account"
    assert result["errors"] == {"base": expected}


async def test_reauth_updates_token_and_reloads(
    hass: HomeAssistant, mock_config_entry, client_cls, api_cls, flow_api_cls
):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "New@Example.com"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["email"] == "new@example.com"
    assert mock_config_entry.data["app_token"] == "flow-token"
    assert mock_config_entry.data["mac"] == MOCK_MAC
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_reauth_refused_email_shows_error(
    hass: HomeAssistant, mock_config_entry, flow_api_cls
):
    flow_api_cls.return_value.login.side_effect = NeatsvorAuthError("refused")
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
