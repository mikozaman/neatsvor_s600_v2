"""Entité de base partagée par les plateformes Neatsvor."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NeatsvorCoordinator


class NeatsvorEntity(CoordinatorEntity[NeatsvorCoordinator]):
    """Entité liée au coordinateur et à l'appareil Neatsvor S600."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NeatsvorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.mac)},
            name="Neatsvor S600",
            manufacturer="Neatsvor",
            model="S600",
        )
