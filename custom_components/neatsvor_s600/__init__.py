"""Intégration Neatsvor S600 (reverse-engineering MQTT + REST, non officielle)."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .api import NeatsvorApiClient, NeatsvorApiError, NeatsvorAuthError
from .const import CONF_EMAIL, CONF_TOKEN
from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator, NeatsvorData

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["vacuum", "sensor", "image", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: NeatsvorConfigEntry) -> bool:
    session = aiohttp_client.async_get_clientsession(hass)
    api = NeatsvorApiClient(session)

    # Le compte REST (pièces/cartes/voix) est en best-effort : aucune
    # entité n'en dépend encore, donc son échec ne doit jamais empêcher le
    # contrôle MQTT (start/stop/retour base) de fonctionner.
    token = entry.data.get(CONF_TOKEN)
    email = entry.data.get(CONF_EMAIL)

    if token:
        api.set_token(token)
    elif email:
        try:
            token = await api.login(email)
        except NeatsvorAuthError:
            _LOGGER.warning(
                "Compte JoyLife refusé pour %s : pièces/cartes/voix "
                "indisponibles, le contrôle MQTT du robot reste fonctionnel",
                entry.title,
            )
            entry.async_start_reauth(hass)
        except NeatsvorApiError:
            _LOGGER.warning(
                "Serveur JoyLife injoignable pour %s : pièces/cartes/voix "
                "indisponibles pour l'instant, le contrôle MQTT reste fonctionnel",
                entry.title,
            )
        else:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: token}
            )
    else:
        _LOGGER.debug(
            "Pas de compte JoyLife configuré pour %s : pièces/cartes/voix "
            "indisponibles, le contrôle MQTT reste fonctionnel",
            entry.title,
        )

    coordinator = NeatsvorCoordinator(hass, entry)
    entry.runtime_data = NeatsvorData(coordinator=coordinator, api=api)

    await coordinator.async_connect()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeatsvorConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
