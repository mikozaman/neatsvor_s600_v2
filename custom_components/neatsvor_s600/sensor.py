"""Capteur de batterie du Neatsvor S600."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NeatsvorConfigEntry, NeatsvorCoordinator
from .entity import NeatsvorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeatsvorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NeatsvorBatterySensor(entry.runtime_data.coordinator)])


class NeatsvorBatterySensor(NeatsvorEntity, SensorEntity):
    """Niveau de batterie (STATE_<mac>.2.2)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: NeatsvorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"neatsvor_s600_{coordinator.mac}_battery"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery
