"""Un bouton « Nettoyer <pièce> » par pièce de la carte du Neatsvor S600."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeatsvorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les boutons dès que la carte est reçue, puis à chaque nouvelle pièce."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    def _add_new_rooms() -> None:
        new = [room_id for room_id in coordinator.data.map_rooms if room_id not in known]
        if new:
            known.update(new)
            async_add_entities(NeatsvorRoomCleanButton(coordinator, room_id) for room_id in new)

    async_add_entities([NeatsvorStartSelectedButton(coordinator)])
    _add_new_rooms()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_rooms))


class NeatsvorRoomCleanButton(NeatsvorEntity, ButtonEntity):
    """Lance le nettoyage d'une pièce avec les réglages enregistrés sur la carte."""

    _attr_translation_key = "clean_room"
    _attr_icon = "mdi:robot-vacuum"

    def __init__(self, coordinator: NeatsvorCoordinator, room_id: int) -> None:
        super().__init__(coordinator)
        self._room_id = room_id
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}_clean_room_{room_id}"
        name = coordinator.data.map_rooms.get(room_id, f"#{room_id}")
        self._attr_translation_placeholders = {"room": name}

    async def async_press(self) -> None:
        await self.coordinator.async_clean_rooms([self._room_id])


class NeatsvorStartSelectedButton(NeatsvorEntity, ButtonEntity):
    """Lance le nettoyage de la cible choisie dans la liste déroulante."""

    _attr_translation_key = "start_selected"
    _attr_icon = "mdi:play-circle"

    def __init__(self, coordinator: NeatsvorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}_start_selected"

    async def async_press(self) -> None:
        await self.coordinator.async_clean_selected()
