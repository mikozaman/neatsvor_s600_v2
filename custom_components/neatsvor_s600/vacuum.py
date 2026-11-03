"""Entité vacuum pour le Neatsvor S600."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
import voluptuous as vol

from .const import COMMAND_START_RESUME, COMMAND_STOP_RETURN, DOMAIN, STATUS_IDLE
from .mqtt_client import NeatsvorMqttClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mac = entry.data["mac"]
    async_add_entities([NeatsvorVacuum(mac)])

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "clean_rooms",
        {
            vol.Required("room_ids"): vol.All(
                [vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))],
                vol.Length(min=1, max=20),
            ),
            vol.Required("fan_level"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
            vol.Required("water_level"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
            vol.Optional("mode", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
        },
        "async_clean_rooms",
    )


class NeatsvorVacuum(StateVacuumEntity):
    """Représente l'aspirateur Neatsvor S600.

    Le firmware ne distingue pas "nettoyage actif" de "retour base actif"
    dans ses messages STATE (même code pour les deux) : on garde donc en
    mémoire la dernière commande envoyée/observée pour lever l'ambiguïté.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.STATE
    )

    def __init__(self, mac: str) -> None:
        self._mac = mac
        self._attr_unique_id = f"neatsvor_s600_{mac}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name="Neatsvor S600",
            manufacturer="Neatsvor",
            model="S600",
        )
        # Hypothèse de départ avant le premier message reçu.
        self._last_command = COMMAND_STOP_RETURN
        self._attr_activity = VacuumActivity.DOCKED
        self._attr_battery_level: int | None = None
        self._online: bool | None = None
        self._client: NeatsvorMqttClient | None = None

    async def async_added_to_hass(self) -> None:
        self._client = NeatsvorMqttClient(
            self._mac, lambda update: self.hass.add_job(self._handle_update, update)
        )
        # MQTT reconnects in its own network thread. Initial cloud unavailability
        # must not prevent the entity from being created in Home Assistant.
        try:
            await self.hass.async_add_executor_job(self._client.connect)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unable to initialize Neatsvor MQTT for %s", self._mac)

    async def async_will_remove_from_hass(self) -> None:
        if self._client is not None:
            await self.hass.async_add_executor_job(self._client.disconnect)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"online": self._online}

    def _handle_update(self, parsed: dict[str, Any]) -> None:
        if "online" in parsed:
            self._online = parsed["online"]
        if parsed.get("battery") is not None:
            self._attr_battery_level = parsed["battery"]

        if "status_code" in parsed:
            status_code = parsed["status_code"]
            if status_code is None:
                # Champ absent du message STATE -> robot en pause.
                self._attr_activity = VacuumActivity.PAUSED
            elif status_code == STATUS_IDLE:
                self._attr_activity = VacuumActivity.DOCKED
            else:
                self._attr_activity = (
                    VacuumActivity.CLEANING
                    if self._last_command == COMMAND_START_RESUME
                    else VacuumActivity.RETURNING
                )

        self.schedule_update_ha_state()

    async def async_start(self) -> None:
        self._last_command = COMMAND_START_RESUME
        await self._async_send("send_command", COMMAND_START_RESUME)

    async def async_stop(self, **kwargs: Any) -> None:
        self._last_command = COMMAND_STOP_RETURN
        await self._async_send("send_command", COMMAND_STOP_RETURN)

    async def async_return_to_base(self, **kwargs: Any) -> None:
        self._last_command = COMMAND_STOP_RETURN
        await self._async_send("send_command", COMMAND_STOP_RETURN)

    async def async_clean_rooms(
        self, room_ids: list[int], fan_level: int, water_level: int, mode: int = 1
    ) -> None:
        """Service neatsvor_s600.clean_rooms — NON VALIDÉ sur le robot réel."""
        if not room_ids or len(room_ids) > 20 or any(
            not 1 <= room_id <= 65535 for room_id in room_ids
        ):
            raise ValueError("room_ids must contain 1 to 20 positive room IDs")
        if not 1 <= fan_level <= 3 or not 1 <= water_level <= 3 or not 1 <= mode <= 5:
            raise ValueError("Unsupported fan, water, or cleaning mode")
        self._last_command = COMMAND_START_RESUME
        await self._async_send(
            "send_room_clean", room_ids, fan_level, water_level, mode
        )

    async def _async_send(self, method_name: str, *args) -> None:
        """Run blocking MQTT publish off the HA event loop."""
        if self._client is None:
            raise RuntimeError("Neatsvor MQTT client is not initialized")
        await self.hass.async_add_executor_job(
            getattr(self._client, method_name), *args
        )
