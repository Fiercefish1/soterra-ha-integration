"""Soterra Home Assistant Integration.

Sends real-time safety device state changes to the Soterra platform via
webhooks. Supports smoke detectors, CO detectors, gas sensors, heat sensors,
and leak detectors.

Setup flow:
1. User pastes their property's Soterra webhook URL
2. User selects which safety entities to monitor
3. Integration sends a discovery payload on setup
4. State changes are pushed automatically from that point

No polling — purely event-driven via HA's state change system.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_ENTITIES,
    CONF_WEBHOOK_URL,
    DISCOVERY_DELAY,
    DOMAIN,
    WEBHOOK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

type SoterraConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: SoterraConfigEntry) -> bool:
    """Set up Soterra from a config entry."""
    webhook_url: str = entry.data[CONF_WEBHOOK_URL]
    entities: list[str] = entry.options.get(CONF_ENTITIES, [])

    if not entities:
        _LOGGER.warning("Soterra integration has no entities configured")
        return True

    # Store runtime data for cleanup
    hass.data.setdefault(DOMAIN, {})

    # Register state change listener
    unsub = _register_listeners(hass, entry, webhook_url, entities)
    hass.data[DOMAIN][entry.entry_id] = {"unsub": unsub}

    # Send discovery payload (delayed slightly so all entities are ready)
    async def _send_initial_discovery(_event: Event | None = None) -> None:
        await _send_discovery(hass, webhook_url, entities)

    if hass.is_running:
        # HA already started — send discovery after a short delay
        entry.async_create_background_task(
            hass,
            _delayed_discovery(hass, webhook_url, entities),
            name="soterra_initial_discovery",
        )
    else:
        # HA still starting — wait for start event
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _send_initial_discovery
            )
        )

    # Re-register listeners when options (entity list) change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info(
        "Soterra integration loaded: monitoring %d entities", len(entities)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SoterraConfigEntry
) -> bool:
    """Unload a config entry."""
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and "unsub" in data:
        data["unsub"]()
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: SoterraConfigEntry
) -> None:
    """Handle options update — re-register listeners with new entity list."""
    _LOGGER.info("Soterra entity list updated, re-registering listeners")

    # Unload and reload to pick up new entities
    await hass.config_entries.async_reload(entry.entry_id)


# ==========================================================================
# State change listeners
# ==========================================================================


@callback
def _register_listeners(
    hass: HomeAssistant,
    entry: SoterraConfigEntry,
    webhook_url: str,
    entities: list[str],
) -> callback:
    """Register state change listeners for monitored entities."""

    async def _state_changed(event: Event) -> None:
        """Handle a state change event."""
        new_state: State | None = event.data.get("new_state")
        old_state: State | None = event.data.get("old_state")

        if new_state is None:
            return

        # Only fire when the state value changes (not attribute-only updates)
        if old_state is not None and old_state.state == new_state.state:
            return

        entity_id = event.data.get("entity_id", "")
        _LOGGER.debug(
            "Soterra state change: %s → %s", entity_id, new_state.state
        )

        await _send_state_update(hass, webhook_url, entity_id, new_state)

    unsub = async_track_state_change_event(hass, entities, _state_changed)
    return unsub


# ==========================================================================
# Webhook payloads
# ==========================================================================


async def _delayed_discovery(
    hass: HomeAssistant, webhook_url: str, entities: list[str]
) -> None:
    """Wait briefly then send discovery."""
    import asyncio

    await asyncio.sleep(DISCOVERY_DELAY)
    await _send_discovery(hass, webhook_url, entities)


async def _send_discovery(
    hass: HomeAssistant, webhook_url: str, entities: list[str]
) -> None:
    """Send a discovery payload with all monitored entities."""
    devices: list[dict[str, Any]] = []

    for entity_id in entities:
        state = hass.states.get(entity_id)
        if state is None:
            continue

        area_entry = None
        try:
            # Resolve area name through entity → device → area chain
            ent_reg = hass.helpers.entity_registry.async_get(hass)
            ent_entry = ent_reg.async_get(entity_id)
            if ent_entry:
                # Entity-level area takes priority
                if ent_entry.area_id:
                    area_reg = hass.helpers.area_registry.async_get(hass)
                    area_entry = area_reg.async_get_area(ent_entry.area_id)
                elif ent_entry.device_id:
                    dev_reg = hass.helpers.device_registry.async_get(hass)
                    dev_entry = dev_reg.async_get(ent_entry.device_id)
                    if dev_entry and dev_entry.area_id:
                        area_reg = hass.helpers.area_registry.async_get(hass)
                        area_entry = area_reg.async_get_area(dev_entry.area_id)
        except Exception:  # noqa: BLE001
            pass  # Area resolution is best-effort

        area_name = area_entry.name if area_entry else "Unknown"

        devices.append(
            {
                "entity_id": entity_id,
                "friendly_name": state.attributes.get(
                    "friendly_name", entity_id
                ),
                "device_class": state.attributes.get("device_class", ""),
                "area": area_name,
                "state": state.state,
                "attributes": {
                    "battery_level": state.attributes.get("battery_level"),
                    "device_class": state.attributes.get("device_class", ""),
                },
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
        "devices": devices,
    }

    success = await _post_webhook(webhook_url, payload)
    if success:
        _LOGGER.info(
            "Soterra discovery sent: %d devices reported", len(devices)
        )
    else:
        _LOGGER.error("Failed to send Soterra discovery payload")


async def _send_state_update(
    hass: HomeAssistant,
    webhook_url: str,
    entity_id: str,
    new_state: State,
) -> None:
    """Send a state update for a single entity."""
    # Build a clean attributes dict (filter out large/irrelevant keys)
    attrs = dict(new_state.attributes)
    clean_attrs: dict[str, Any] = {}
    for key in (
        "battery_level",
        "device_class",
        "friendly_name",
        "tampered",
        "signal_strength",
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
    """Post a JSON payload to the Soterra webhook."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    _LOGGER.warning(
                        "Soterra webhook returned %d: %s", resp.status, body
                    )
                    return False
                return True
    except aiohttp.ClientError as err:
        _LOGGER.error("Soterra webhook request failed: %s", err)
        return False
    except TimeoutError:
        _LOGGER.error("Soterra webhook request timed out")
        return False
