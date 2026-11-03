"""Coordinateur push du Neatsvor S600 : possède le client MQTT et l'état du robot.

Le firmware ne distingue pas « nettoyage actif » de « retour base actif »
dans ses messages STATE (même code pour les deux) : on garde donc en
mémoire la dernière commande envoyée pour lever l'ambiguïté.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.components.vacuum import VacuumActivity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import NeatsvorApiClient
from .const import COMMAND_START_RESUME, COMMAND_STOP_RETURN, DOMAIN, STATUS_IDLE
from .mqtt_client import NeatsvorMqttClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NeatsvorState:
    """État du robot tel que reconstruit à partir des messages MQTT."""

    activity: VacuumActivity = VacuumActivity.DOCKED
    battery: int | None = None
    online: bool | None = None
    # Hypothèse de départ avant le premier message reçu.
    last_command: int = COMMAND_STOP_RETURN
    connected: bool = False


def apply_update(state: NeatsvorState, parsed: dict[str, Any]) -> NeatsvorState:
    """Applique un message MQTT décodé à l'état courant (fonction pure)."""
    changes: dict[str, Any] = {}
    if "online" in parsed:
        changes["online"] = parsed["online"]
    if parsed.get("battery") is not None:
        changes["battery"] = parsed["battery"]
    if "status_code" in parsed:
        status_code = parsed["status_code"]
        if status_code is None:
            # Champ absent du message STATE -> robot en pause.
            changes["activity"] = VacuumActivity.PAUSED
        elif status_code == STATUS_IDLE:
            changes["activity"] = VacuumActivity.DOCKED
        else:
            changes["activity"] = (
                VacuumActivity.CLEANING
                if state.last_command == COMMAND_START_RESUME
                else VacuumActivity.RETURNING
            )
    return replace(state, **changes)


class NeatsvorCoordinator(DataUpdateCoordinator[NeatsvorState]):
    """Coordinateur sans polling : les mises à jour arrivent par MQTT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.mac: str = entry.data["mac"]
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Neatsvor S600 {self.mac}",
            update_interval=None,
        )
        self.data = NeatsvorState()
        self._closing = False
        self._outage_logged = False
        self._client = NeatsvorMqttClient(self.mac, self._on_mqtt_update, self._on_mqtt_connection)

    # -- Cycle de vie ------------------------------------------------------
    async def async_connect(self) -> None:
        """Démarre MQTT. Une panne initiale du cloud ne doit pas bloquer le setup."""
        try:
            await self.hass.async_add_executor_job(self._client.connect)
        except Exception:
            _LOGGER.exception("Unable to initialize Neatsvor MQTT for %s", self.mac)

    async def async_shutdown(self) -> None:
        """Arrête MQTT ; les callbacks tardifs du thread paho sont ignorés."""
        self._closing = True
        await super().async_shutdown()
        try:
            await self.hass.async_add_executor_job(self._client.disconnect)
        except Exception:
            _LOGGER.exception("Error while stopping Neatsvor MQTT for %s", self.mac)

    # -- Callbacks du thread paho ---------------------------------------------
    def _on_mqtt_update(self, parsed: dict[str, Any]) -> None:
        self._schedule(self._apply_update, parsed)

    def _on_mqtt_connection(self, connected: bool) -> None:
        self._schedule(self._apply_connection, connected)

    def _schedule(self, func, *args) -> None:
        if self._closing:
            return
        try:
            self.hass.loop.call_soon_threadsafe(func, *args)
        except RuntimeError:  # boucle d'événements déjà fermée
            _LOGGER.debug("Event loop closed, dropping Neatsvor MQTT callback")

    @callback
    def _apply_update(self, parsed: dict[str, Any]) -> None:
        if self._closing:
            return
        self.async_set_updated_data(apply_update(self.data, parsed))

    @callback
    def _apply_connection(self, connected: bool) -> None:
        if self._closing:
            return
        if connected:
            if self._outage_logged:
                _LOGGER.info("Connexion au cloud Neatsvor rétablie pour %s", self.mac)
            self._outage_logged = False
        elif not self._outage_logged:
            _LOGGER.warning("Connexion au cloud Neatsvor perdue pour %s", self.mac)
            self._outage_logged = True
        self.async_set_updated_data(replace(self.data, connected=connected))

    # -- Commandes -----------------------------------------------------------
    async def async_start(self) -> None:
        await self._async_send("send_command", COMMAND_START_RESUME)
        self._remember_command(COMMAND_START_RESUME)

    async def async_stop(self) -> None:
        await self._async_send("send_command", COMMAND_STOP_RETURN)
        self._remember_command(COMMAND_STOP_RETURN)

    async def async_return_home(self) -> None:
        await self._async_send("send_command", COMMAND_STOP_RETURN)
        self._remember_command(COMMAND_STOP_RETURN)

    async def async_clean_rooms(
        self, room_ids: list[int], fan_level: int, water_level: int, mode: int = 1
    ) -> None:
        """Service neatsvor_s600.clean_rooms — NON VALIDÉ sur le robot réel."""
        await self._async_send("send_room_clean", room_ids, fan_level, water_level, mode)
        self._remember_command(COMMAND_START_RESUME)

    def _remember_command(self, command: int) -> None:
        self.async_set_updated_data(replace(self.data, last_command=command))

    async def _async_send(self, method_name: str, *args: Any) -> None:
        """Exécute la publication MQTT bloquante hors de la boucle HA."""
        if not self._client.is_connected():
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_connected")
        try:
            await self.hass.async_add_executor_job(getattr(self._client, method_name), *args)
        except OSError as err:  # ConnectionError et TimeoutError en héritent
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from err


@dataclass
class NeatsvorData:
    """Objets partagés stockés dans entry.runtime_data."""

    coordinator: NeatsvorCoordinator
    api: NeatsvorApiClient


type NeatsvorConfigEntry = ConfigEntry[NeatsvorData]
