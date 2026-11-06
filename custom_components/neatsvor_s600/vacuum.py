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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform

from .const import (
    FAN_LEVEL_MAX,
    FAN_LEVEL_MIN,
    MODE_MAX,
    MODE_MIN,
    USE_MAP_SETTING,
    WATER_LEVEL_MAX,
    WATER_LEVEL_MIN,
)
from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity


def _level(minimum: int, maximum: int):
    """-1 (réglage enregistré sur la carte) ou une valeur explicite dans la plage."""
    return vol.All(
        vol.Coerce(int),
        vol.Any(USE_MAP_SETTING, vol.Range(min=minimum, max=maximum)),
    )


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
            # Noms (« Cuisine ») et/ou identifiants ; au moins l'un des deux est requis.
            vol.Optional("rooms"): vol.All(
                cv.ensure_list, [vol.Any(int, cv.string)], vol.Length(min=1, max=20)
            ),
            vol.Optional("room_ids"): vol.All(
                cv.ensure_list,
                [vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))],
                vol.Length(min=1, max=20),
            ),
            vol.Optional("fan_level", default=USE_MAP_SETTING): _level(
                FAN_LEVEL_MIN, FAN_LEVEL_MAX
            ),
            vol.Optional("water_level", default=USE_MAP_SETTING): _level(
                WATER_LEVEL_MIN, WATER_LEVEL_MAX
            ),
            vol.Optional("mode", default=USE_MAP_SETTING): _level(MODE_MIN, MODE_MAX),
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
        data = self.coordinator.data
        return {"online": data.online, "rooms": data.map_rooms}

    async def async_start(self) -> None:
        await self.coordinator.async_start()

    async def async_stop(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self.coordinator.async_return_home()

    async def async_clean_rooms(
        self,
        room_ids: list[int] | None = None,
        rooms: list[int | str] | None = None,
        fan_level: int = USE_MAP_SETTING,
        water_level: int = USE_MAP_SETTING,
        mode: int = USE_MAP_SETTING,
    ) -> None:
        """Service neatsvor_s600.clean_rooms (validé avec les niveaux à -1)."""
        if not room_ids and not rooms:
            raise ServiceValidationError("Provide 'rooms' (names or ids) or 'room_ids'")
        ids = list(room_ids or [])
        for room_id in self.coordinator.resolve_rooms(list(rooms or [])):
            if room_id not in ids:
                ids.append(room_id)
        await self.coordinator.async_clean_rooms(ids, fan_level, water_level, mode)
