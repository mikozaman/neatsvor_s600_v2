"""Tests for the diagnostics download."""
from __future__ import annotations

import json

from custom_components.neatsvor_s600.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

from .conftest import MOCK_MAC


async def test_diagnostics_redacts_identifiers(
    hass: HomeAssistant, mock_config_entry, client_cls, api_cls
):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    client_cls.call_args.args[1]({"status_code": 2, "battery": 63})
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["state"] == {
        "activity": "returning",
        "battery": 63,
        "online": None,
        "connected": False,
    }
    assert set(result["entry"]) == {"mac", "email", "app_token"}
    dumped = json.dumps(result)
    for secret in (MOCK_MAC, "user@example.com", '"tok"'):
        assert secret not in dumped
