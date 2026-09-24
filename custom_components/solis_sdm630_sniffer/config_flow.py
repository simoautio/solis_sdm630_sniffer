"""UI configuration; no active probing of the meter or gateway."""

from __future__ import annotations

import math
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CREATE_UTILITY_METERS,
    CONF_GRID_IMPORT_SIGN,
    CONF_TIMEOUT,
    CONF_TOPIC,
    DEFAULT_GRID_IMPORT_SIGN,
    DEFAULT_TIMEOUT,
    DEFAULT_TOPIC,
    DOMAIN,
)
from .utility_meters import UtilityMeterSetupError, async_create_utility_meters


def _timeout_schema(default: float) -> dict:
    return {
        vol.Required(CONF_TIMEOUT, default=default): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=86400,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
    }


def _valid_timeout(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 1 <= value <= 86400
    )


class SnifferConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one exact MQTT topic per meter stream."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Require built-in MQTT, then collect the topic and timeout."""
        if not mqtt.mqtt_config_entry_enabled(self.hass):
            return self.async_abort(reason="mqtt_required")
        errors = {}
        if user_input is not None:
            topic = user_input[CONF_TOPIC]
            try:
                mqtt.valid_publish_topic(topic)  # Exact topic: wildcards are unsafe.
            except (vol.Invalid, ValueError, TypeError):
                errors[CONF_TOPIC] = "invalid_topic"
            if not _valid_timeout(user_input[CONF_TIMEOUT]):
                errors[CONF_TIMEOUT] = "invalid_timeout"
            if not errors:
                await self.async_set_unique_id(topic)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Solis SDM630 Sniffer", data=user_input
                )
        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TOPIC, default=defaults.get(CONF_TOPIC, DEFAULT_TOPIC)
                    ): str,
                    **_timeout_schema(defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SnifferOptionsFlow:
        """Return a modern options flow without assigning config_entry."""
        return SnifferOptionsFlow()


class SnifferOptionsFlow(OptionsFlow):
    """Configure power direction, availability, and optional energy helpers."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        default_sign = self.config_entry.options.get(
            CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN
        )
        if user_input is not None:
            sign = user_input.get(CONF_GRID_IMPORT_SIGN, default_sign)
            if not _valid_timeout(user_input[CONF_TIMEOUT]):
                errors[CONF_TIMEOUT] = "invalid_timeout"
            if sign not in ("positive", "negative"):
                errors[CONF_GRID_IMPORT_SIGN] = "invalid_direction"
            if not errors and user_input.get(CONF_CREATE_UTILITY_METERS, False):
                try:
                    await async_create_utility_meters(self.hass, self.config_entry)
                except UtilityMeterSetupError as err:
                    errors["base"] = str(err)
            if not errors:
                # Creating helpers is a one-time action, not a persistent startup
                # instruction. Future reloads must not recreate user-deleted helpers.
                options = dict(self.config_entry.options)
                options.update(
                    {
                        CONF_TIMEOUT: user_input[CONF_TIMEOUT],
                        CONF_GRID_IMPORT_SIGN: sign,
                    }
                )
                return self.async_create_entry(title="", data=options)
        default = self.config_entry.options.get(
            CONF_TIMEOUT, self.config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        )
        schema = {
            **_timeout_schema(default),
            vol.Required(
                CONF_GRID_IMPORT_SIGN, default=default_sign
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["positive", "negative"],
                    translation_key=CONF_GRID_IMPORT_SIGN,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_CREATE_UTILITY_METERS, default=False
            ): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), user_input
            ),
            errors=errors,
        )
