"""Soterra diagnostic sensor."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICES, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Soterra status sensor."""
    async_add_entities([SoterraStatusSensor(entry)])


class SoterraStatusSensor(SensorEntity):
    """Shows how many devices are being monitored."""

    _attr_has_entity_name = True
    _attr_name = "Monitored Devices"
    _attr_icon = "mdi:shield-check"
    _attr_entity_category = "diagnostic"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialise."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Soterra Safety Monitoring",
            "manufacturer": "Soterra",
            "model": "Webhook Integration",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> int:
        """Return number of monitored devices."""
        return len(self._entry.options.get(CONF_DEVICES, []))

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        return {
            "monitored_device_ids": self._entry.options.get(CONF_DEVICES, []),
        }
