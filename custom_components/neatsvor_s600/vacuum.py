"""Entité vacuum pour le Neatsvor S600."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform

from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeatsvorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NeatsvorVacuum(entry.runtime_data.coordinator)])

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


class NeatsvorVacuum(NeatsvorEntity, StateVacuumEntity):
    """Représente l'aspirateur Neatsvor S600 (état poussé par le coordinateur)."""

    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.STATE
    )

    def __init__(self, coordinator: NeatsvorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}"

    @property
    def activity(self) -> VacuumActivity:
        return self.coordinator.data.activity

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"online": self.coordinator.data.online}

    async def async_start(self) -> None:
        await self.coordinator.async_start()

    async def async_stop(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.async_return_home()

    async def async_clean_rooms(
        self, room_ids: list[int], fan_level: int, water_level: int, mode: int = 1
    ) -> None:
        """Service neatsvor_s600.clean_rooms — NON VALIDÉ sur le robot réel."""
        await self.coordinator.async_clean_rooms(room_ids, fan_level, water_level, mode)
