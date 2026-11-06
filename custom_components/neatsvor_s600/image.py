"""Entité image : carte du Neatsvor S600 rendue depuis le topic MAP_<mac>."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeatsvorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NeatsvorMapImage(hass, entry.runtime_data.coordinator)])


class NeatsvorMapImage(NeatsvorEntity, ImageEntity):
    """Dernière carte reçue (aucune image tant que le robot n'a rien publié)."""

    _attr_translation_key = "map"
    _attr_content_type = "image/png"

    def __init__(self, hass: HomeAssistant, coordinator: NeatsvorCoordinator) -> None:
        NeatsvorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}_map"

    @property
    def image_last_updated(self) -> datetime | None:
        return self.coordinator.data.map_updated

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "rooms": data.map_rooms,
            "room_settings": data.map_room_settings,
            "size": data.map_size,
            "dock_raw": data.map_dock,
            "robot_raw": data.map_robot,
        }

    async def async_image(self) -> bytes | None:
        return self.coordinator.data.map_png
