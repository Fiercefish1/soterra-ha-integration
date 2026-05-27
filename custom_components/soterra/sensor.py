"""Soterra diagnostic sensors."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICES, DOMAIN, SIGNAL_PUBLISH


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Soterra status sensors."""
    async_add_entities(
        [
            SoterraDeviceCountSensor(entry),
            SoterraLastPublishSensor(hass, entry),
        ]
    )


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Shared device info so all Soterra sensors group under one device."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Soterra Safety Monitoring",
        "manufacturer": "Soterra",
        "model": "Webhook Integration",
        "entry_type": "service",
    }


class SoterraDeviceCountSensor(SensorEntity):
    """Shows how many devices are being monitored."""

    _attr_has_entity_name = True
    _attr_name = "Monitored Devices"
    _attr_icon = "mdi:shield-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialise."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = _device_info(entry)

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


class SoterraLastPublishSensor(SensorEntity):
    """Shows the timestamp of the last successful publish to the webhook."""

    _attr_has_entity_name = True
    _attr_name = "Last Publish"
    _attr_icon = "mdi:cloud-upload"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_publish"
        self._attr_device_info = _device_info(entry)

    def _runtime(self) -> dict[str, Any]:
        """Return this entry's runtime state, or an empty dict."""
        return self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last successful publish."""
        return self._runtime().get("last_publish")

    @property
    def extra_state_attributes(self) -> dict:
        """Return details about the last publish."""
        runtime = self._runtime()
        return {
            "last_payload_type": runtime.get("last_payload_type"),
            "last_entity_count": runtime.get("last_publish_count"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to publish notifications."""
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                f"{SIGNAL_PUBLISH}_{self._entry.entry_id}",
                self._handle_publish,
            )
        )

    @callback
    def _handle_publish(self) -> None:
        """Refresh state when a publish succeeds."""
        self.async_write_ha_state()
