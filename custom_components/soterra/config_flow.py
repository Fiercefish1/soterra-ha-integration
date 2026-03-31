"""Config flow for Soterra integration — device-centric."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_DEVICES,
    CONF_WEBHOOK_URL,
    DOMAIN,
    EXTRA_DEVICE_CLASSES,
    SAFETY_DEVICE_CLASSES,
    WEBHOOK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


# =========================================================================
# Helpers: discover HA devices that have safety-related entities
# =========================================================================


def discover_safety_devices(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Scan registries for devices that own at least one safety entity.

    Returns {device_id: {name, manufacturer, model, area, entities: [...]}}
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = hass.helpers.area_registry.async_get(hass)

    # Step 1: find all safety binary_sensor entities and their parent devices
    safety_entity_ids_by_device: dict[str, list[er.RegistryEntry]] = {}

    for entry in ent_reg.entities.values():
        if entry.disabled:
            continue
        if entry.device_id is None:
            continue

        state = hass.states.get(entry.entity_id)
        device_class = (
            state.attributes.get("device_class")
            if state
            else entry.original_device_class
        )

        is_safety = (
            entry.domain == "binary_sensor"
            and device_class in SAFETY_DEVICE_CLASSES
        )
        if is_safety:
            safety_entity_ids_by_device.setdefault(entry.device_id, []).append(
                entry
            )

    # Step 2: for each device with safety entities, also collect battery/tamper
    devices: dict[str, dict[str, Any]] = {}

    for device_id, safety_entries in safety_entity_ids_by_device.items():
        dev_entry = dev_reg.async_get(device_id)
        if dev_entry is None:
            continue

        # Resolve area
        area_name = "Unknown"
        if dev_entry.area_id:
            area = area_reg.async_get_area(dev_entry.area_id)
            if area:
                area_name = area.name

        # Collect ALL relevant entities for this device
        entities: list[dict[str, Any]] = []

        for ent in ent_reg.entities.values():
            if ent.disabled or ent.device_id != device_id:
                continue

            state = hass.states.get(ent.entity_id)
            device_class = (
                state.attributes.get("device_class")
                if state
                else ent.original_device_class
            )

            is_safety_ent = (
                ent.domain == "binary_sensor"
                and device_class in SAFETY_DEVICE_CLASSES
            )
            is_extra_ent = device_class in EXTRA_DEVICE_CLASSES

            if is_safety_ent or is_extra_ent:
                entity_state = state.state if state else "unknown"
                entities.append(
                    {
                        "entity_id": ent.entity_id,
                        "device_class": device_class or "",
                        "domain": ent.domain,
                        "friendly_name": (
                            state.attributes.get("friendly_name", ent.entity_id)
                            if state
                            else ent.original_name or ent.entity_id
                        ),
                        "state": entity_state,
                        "unit": (
                            state.attributes.get("unit_of_measurement", "")
                            if state
                            else ""
                        ),
                    }
                )

        if not entities:
            continue

        # Device display name
        device_name = (
            dev_entry.name_by_user
            or dev_entry.name
            or f"Device {device_id[:8]}"
        )

        devices[device_id] = {
            "name": device_name,
            "manufacturer": dev_entry.manufacturer or "",
            "model": dev_entry.model or "",
            "area": area_name,
            "entities": entities,
        }

    return devices


# =========================================================================
# Config Flow
# =========================================================================


class SoterraConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Soterra."""

    VERSION = 2  # Bumped from 1 — new device-centric model

    def __init__(self) -> None:
        """Initialise flow."""
        self._webhook_url: str | None = None
        self._discovered_devices: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Enter webhook URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            webhook_url = user_input[CONF_WEBHOOK_URL].strip().rstrip("/")

            if not webhook_url.startswith("https://"):
                errors["base"] = "invalid_url"
            else:
                valid = await self._test_webhook(webhook_url)
                if not valid:
                    errors["base"] = "cannot_connect"
                else:
                    self._webhook_url = webhook_url
                    return await self.async_step_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WEBHOOK_URL): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.URL
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Select safety devices (not entities)."""
        errors: dict[str, str] = {}

        # Discover available devices
        self._discovered_devices = await self.hass.async_add_executor_job(
            discover_safety_devices, self.hass
        )

        if not self._discovered_devices:
            return self.async_abort(reason="no_safety_devices")

        if user_input is not None:
            selected = user_input.get(CONF_DEVICES, [])
            if not selected:
                errors["base"] = "no_devices"
            else:
                await self.async_set_unique_id(self._webhook_url)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Soterra Home Assistant Integration",
                    data={CONF_WEBHOOK_URL: self._webhook_url},
                    options={CONF_DEVICES: selected},
                )

        # Build multi-select options: {device_id: "Device Name (Area)"}
        device_options: dict[str, str] = {}
        for dev_id, info in self._discovered_devices.items():
            entity_summary = ", ".join(
                sorted(
                    {
                        e["device_class"]
                        for e in info["entities"]
                        if e["device_class"] in SAFETY_DEVICE_CLASSES
                    }
                )
            )
            label = f"{info['name']} — {info['area']}"
            if entity_summary:
                label += f" ({entity_summary})"
            device_options[dev_id] = label

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES): vol.In(device_options),
                }
            )
            if len(device_options) == 1
            else vol.Schema(
                {
                    vol.Required(CONF_DEVICES): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=dev_id, label=label
                                )
                                for dev_id, label in device_options.items()
                            ],
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def _test_webhook(self, url: str) -> bool:
        """Test webhook with an empty discovery."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"type": "discovery", "devices": []},
                    timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
                ) as resp:
                    return resp.status < 500
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.warning("Failed to connect to Soterra webhook: %s", url)
            return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return SoterraOptionsFlow(config_entry)


class SoterraOptionsFlow(OptionsFlow):
    """Handle options — modify which devices are monitored."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage device selection."""
        discovered = await self.hass.async_add_executor_job(
            discover_safety_devices, self.hass
        )

        if user_input is not None:
            return self.async_create_entry(
                data={CONF_DEVICES: user_input.get(CONF_DEVICES, [])}
            )

        current = self._config_entry.options.get(CONF_DEVICES, [])

        device_options = [
            selector.SelectOptionDict(
                value=dev_id,
                label=f"{info['name']} — {info['area']}",
            )
            for dev_id, info in discovered.items()
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICES, default=current
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
