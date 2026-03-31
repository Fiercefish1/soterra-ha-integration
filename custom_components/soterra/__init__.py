"""Soterra Home Assistant Integration — device-centric integration.

Monitors HA devices (not raw entities) that contain safety-related sensors.
Sends device-grouped discovery payloads and per-entity state updates to the
Soterra webhook.

Setup flow:
1. User pastes webhook URL
2. Integration auto-discovers devices with safety entities
3. User selects which devices to monitor (sees device names, not entity IDs)
4. Discovery sends device-centric payload (device → entities)
5. State changes push per-entity for real-time responsiveness
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .config_flow import discover_safety_devices
from .const import (
    CONF_DEVICES,
    CONF_WEBHOOK_URL,
    DISCOVERY_DELAY,
    DOMAIN,
    EXTRA_DEVICE_CLASSES,
    SAFETY_DEVICE_CLASSES,
    WEBHOOK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

type SoterraConfigEntry = ConfigEntry


# =========================================================================
# Setup / Teardown
# =========================================================================


async def async_setup_entry(hass: HomeAssistant, entry: SoterraConfigEntry) -> bool:
    """Set up Soterra from a config entry."""
    webhook_url: str = entry.data[CONF_WEBHOOK_URL]
    selected_device_ids: list[str] = entry.options.get(CONF_DEVICES, [])

    if not selected_device_ids:
        _LOGGER.warning("Soterra: no devices selected")
        return True

    hass.data.setdefault(DOMAIN, {})

    # Resolve all trackable entity IDs from selected devices
    entity_ids = _resolve_entity_ids(hass, selected_device_ids)
    if not entity_ids:
        _LOGGER.warning("Soterra: selected devices have no trackable entities")
        return True

    _LOGGER.info(
        "Soterra: monitoring %d devices (%d entities)",
        len(selected_device_ids),
        len(entity_ids),
    )

    # Register state listeners
    unsub = _register_listeners(hass, entry, webhook_url, entity_ids)
    hass.data[DOMAIN][entry.entry_id] = {
        "unsub": unsub,
        "device_ids": selected_device_ids,
    }

    # Send discovery
    if hass.is_running:
        entry.async_create_background_task(
            hass,
            _delayed_discovery(hass, webhook_url, selected_device_ids),
            name="soterra_initial_discovery",
        )
    else:
        async def _on_start(_event: Event) -> None:
            await _delayed_discovery(hass, webhook_url, selected_device_ids)

        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_start)
        )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SoterraConfigEntry
) -> bool:
    """Unload."""
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and "unsub" in data:
        data["unsub"]()
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: SoterraConfigEntry
) -> None:
    """Handle device list change — reload."""
    _LOGGER.info("Soterra: device selection changed, reloading")
    await hass.config_entries.async_reload(entry.entry_id)


# =========================================================================
# Entity resolution
# =========================================================================


def _resolve_entity_ids(
    hass: HomeAssistant, device_ids: list[str]
) -> list[str]:
    """Resolve all trackable entity IDs from a list of HA device IDs."""
    ent_reg = er.async_get(hass)
    entity_ids: list[str] = []

    device_id_set = set(device_ids)
    for entry in ent_reg.entities.values():
        if entry.disabled or entry.device_id not in device_id_set:
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
        is_extra = device_class in EXTRA_DEVICE_CLASSES

        if is_safety or is_extra:
            entity_ids.append(entry.entity_id)

    return entity_ids


# =========================================================================
# State change listeners
# =========================================================================


@callback
def _register_listeners(
    hass: HomeAssistant,
    entry: SoterraConfigEntry,
    webhook_url: str,
    entity_ids: list[str],
) -> callback:
    """Register listeners for all tracked entities."""

    async def _state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        old_state: State | None = event.data.get("old_state")
        if new_state is None:
            return
        if old_state is not None and old_state.state == new_state.state:
            return

        entity_id = event.data.get("entity_id", "")
        _LOGGER.debug("Soterra state: %s → %s", entity_id, new_state.state)
        await _send_state_update(hass, webhook_url, entity_id, new_state)

    return async_track_state_change_event(hass, entity_ids, _state_changed)


# =========================================================================
# Webhook payloads
# =========================================================================


async def _delayed_discovery(
    hass: HomeAssistant, webhook_url: str, device_ids: list[str]
) -> None:
    """Wait briefly then send device-centric discovery."""
    await asyncio.sleep(DISCOVERY_DELAY)
    await _send_discovery(hass, webhook_url, device_ids)


async def _send_discovery(
    hass: HomeAssistant, webhook_url: str, device_ids: list[str]
) -> None:
    """Send a device-centric discovery payload."""
    all_devices = await hass.async_add_executor_job(
        discover_safety_devices, hass
    )

    payload_devices: list[dict[str, Any]] = []
    for dev_id in device_ids:
        info = all_devices.get(dev_id)
        if not info:
            continue

        payload_devices.append(
            {
                "device_id": dev_id,
                "device_name": info["name"],
                "manufacturer": info["manufacturer"],
                "model": info["model"],
                "area": info["area"],
                "entities": [
                    {
                        "entity_id": e["entity_id"],
                        "device_class": e["device_class"],
                        "friendly_name": e["friendly_name"],
                        "state": e["state"],
                        "unit": e.get("unit", ""),
                    }
                    for e in info["entities"]
                ],
            }
        )

    ha_version = "unknown"
    try:
        ha_version = hass.config.version or "unknown"
    except Exception:  # noqa: BLE001
        pass

    payload = {
        "type": "discovery",
        "ha_version": ha_version,
        "devices": payload_devices,
    }

    ok = await _post_webhook(webhook_url, payload)
    if ok:
        _LOGGER.info("Soterra discovery: %d devices sent", len(payload_devices))
    else:
        _LOGGER.error("Soterra discovery failed")


async def _send_state_update(
    hass: HomeAssistant,
    webhook_url: str,
    entity_id: str,
    new_state: State,
) -> None:
    """Send per-entity state update (unchanged format — webapp routes it)."""
    attrs = dict(new_state.attributes)
    clean_attrs: dict[str, Any] = {}
    for key in (
        "battery_level",
        "device_class",
        "friendly_name",
        "tampered",
        "signal_strength",
        "unit_of_measurement",
    ):
        if key in attrs:
            clean_attrs[key] = attrs[key]

    payload = {
        "type": "state_update",
        "devices": [
            {
                "entity_id": entity_id,
                "state": new_state.state,
                "attributes": clean_attrs,
                "last_changed": new_state.last_changed.isoformat(),
            }
        ],
    }

    await _post_webhook(webhook_url, payload)


async def _post_webhook(url: str, payload: dict[str, Any]) -> bool:
    """Post JSON to Soterra webhook."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    _LOGGER.warning("Soterra webhook %d: %s", resp.status, body)
                    return False
                return True
    except aiohttp.ClientError as err:
        _LOGGER.error("Soterra webhook error: %s", err)
        return False
    except TimeoutError:
        _LOGGER.error("Soterra webhook timeout")
        return False
