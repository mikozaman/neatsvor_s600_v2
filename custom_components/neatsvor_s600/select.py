"""Liste déroulante « Cible de nettoyage » : global ou une pièce de la carte."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity

GLOBAL_OPTION = "Global"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeatsvorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NeatsvorCleanTargetSelect(entry.runtime_data.coordinator)])


class NeatsvorCleanTargetSelect(NeatsvorEntity, SelectEntity):
    """Choisit ce que le bouton « Lancer le nettoyage » va nettoyer.

    Choisir une valeur ne démarre rien : seul le bouton lance le robot.
    """

    _attr_translation_key = "clean_target"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: NeatsvorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}_clean_target"

    @property
    def options(self) -> list[str]:
        rooms = self.coordinator.data.map_rooms
        return [GLOBAL_OPTION, *(rooms[room_id] for room_id in sorted(rooms))]

    @property
    def current_option(self) -> str:
        target = self.coordinator.clean_target
        return self.coordinator.data.map_rooms.get(target, GLOBAL_OPTION)

    async def async_select_option(self, option: str) -> None:
        if option == GLOBAL_OPTION:
            self.coordinator.clean_target = None
        else:
            by_name = {name: room_id for room_id, name in self.coordinator.data.map_rooms.items()}
            if option not in by_name:
                raise ServiceValidationError(f"Unknown room: {option}")
            self.coordinator.clean_target = by_name[option]
        self.async_write_ha_state()
