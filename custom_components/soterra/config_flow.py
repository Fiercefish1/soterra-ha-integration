"""Config flow for Soterra integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ENTITIES,
    CONF_WEBHOOK_URL,
    DOMAIN,
    SAFETY_DEVICE_CLASSES,
    WEBHOOK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SoterraConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Soterra."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow."""
        self._webhook_url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Enter webhook URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            webhook_url = user_input[CONF_WEBHOOK_URL].strip().rstrip("/")

            # Validate URL format
            if not webhook_url.startswith("https://"):
                errors["base"] = "invalid_url"
            else:
                # Test the webhook with a ping
                valid = await self._test_webhook(webhook_url)
                if not valid:
                    errors["base"] = "cannot_connect"
                else:
                    self._webhook_url = webhook_url
                    return await self.async_step_entities()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WEBHOOK_URL): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://app.soterra.co",
            },
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Select safety device entities."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entities = user_input.get(CONF_ENTITIES, [])
            if not entities:
                errors["base"] = "no_entities"
            else:
                # Prevent duplicate config entries for the same webhook
                await self.async_set_unique_id(self._webhook_url)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Soterra Safety Monitoring",
                    data={CONF_WEBHOOK_URL: self._webhook_url},
                    options={CONF_ENTITIES: entities},
                )

        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTITIES): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            multiple=True,
                            filter=selector.EntityFilterSelectorConfig(
                                domain="binary_sensor",
                                device_class=SAFETY_DEVICE_CLASSES,
                            ),
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def _test_webhook(self, url: str) -> bool:
        """Test the webhook URL by sending a minimal ping payload."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"type": "discovery", "devices": []},
                    timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
                ) as resp:
                    # Accept 200 (success) or 404 (valid Convex route, bad secret)
                    # Reject network errors and 5xx
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
    """Handle options flow — modify which entities are monitored."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage entity selection."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_ENTITIES: user_input.get(CONF_ENTITIES, [])}
            )

        current = self._config_entry.options.get(CONF_ENTITIES, [])

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENTITIES, default=current
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            multiple=True,
                            filter=selector.EntityFilterSelectorConfig(
                                domain="binary_sensor",
                                device_class=SAFETY_DEVICE_CLASSES,
                            ),
                        )
                    ),
                }
            ),
        )
