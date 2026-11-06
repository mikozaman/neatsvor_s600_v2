"""Diagnostics du Neatsvor S600 (MAC, e-mail et token masqués)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_TOKEN
from .coordinator import NeatsvorConfigEntry

TO_REDACT = {"mac", CONF_EMAIL, CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NeatsvorConfigEntry
) -> dict[str, Any]:
    state = entry.runtime_data.coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "state": {
            "activity": str(state.activity),
            "battery": state.battery,
            "online": state.online,
            "connected": state.connected,
            "map_size": state.map_size,
            "map_rooms": len(state.map_rooms),
            "map_updated": state.map_updated.isoformat() if state.map_updated else None,
        },
    }
