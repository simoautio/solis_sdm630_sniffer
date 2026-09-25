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
    CONF_GRID_IMPORT_SIGN,
    CONF_LOGGER_HOST,
    CONF_LOGGER_INTERVAL,
    CONF_LOGGER_PORT,
    CONF_LOGGER_UNIT,
    CONF_METER_REVERSED,
    CONF_MODE,
    CONF_TIMEOUT,
    CONF_TOPIC,
    CONF_UPDATE_INTERVAL,
    CONF_UTILITY_CYCLES,
    CONF_UTILITY_SOURCES,
    DEFAULT_GRID_IMPORT_SIGN,
    DEFAULT_LOGGER_INTERVAL,
    DEFAULT_LOGGER_PORT,
    DEFAULT_LOGGER_UNIT,
    DEFAULT_TIMEOUT,
    DEFAULT_TOPIC,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER_TITLE,
    METER_TITLE,
    MODES,
)
from .utility_meters import (
    CYCLES,
    DEFAULT_CYCLES,
    DEFAULT_SOURCES,
    SOURCES,
    UtilityMeterSetupError,
    async_create_utility_meters,
)

# (option, minimum, maximum, default) for the optional read-only logger.
_LOGGER_NUMBERS = (
    (CONF_LOGGER_PORT, 1, 65535, DEFAULT_LOGGER_PORT),
    (CONF_LOGGER_UNIT, 1, 247, DEFAULT_LOGGER_UNIT),
    (CONF_LOGGER_INTERVAL, 10, 3600, DEFAULT_LOGGER_INTERVAL),
)


def _seconds_schema(default: float, key: str = CONF_TIMEOUT) -> dict:
    return {
        vol.Required(key, default=default): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=86400,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
    }


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _valid_host(host: Any) -> bool:
    """A bare hostname or IPv4 address; URLs and ports belong elsewhere."""
    return (
        isinstance(host, str)
        and 0 < len(host) <= 253
        and not any(char in host for char in "/:@ \t")
    )


def _logger_options(user_input: dict, current: dict, errors: dict) -> dict:
    """Validate logger settings; an empty host disables polling."""
    host = (user_input.get(CONF_LOGGER_HOST) or "").strip()
    if not host:
        return {}
    if not _valid_host(host):
        errors[CONF_LOGGER_HOST] = "invalid_logger"
    options = {CONF_LOGGER_HOST: host}
    for key, minimum, maximum, default in _LOGGER_NUMBERS:
        value = user_input.get(key, current.get(key, default))
        if not _number(value, minimum, maximum):
            errors[key] = "invalid_logger"
        else:
            options[key] = int(value)
    return options


def _host_schema(host: str | None) -> dict:
    return {vol.Optional(CONF_LOGGER_HOST, description={"suggested_value": host}): str}


def _logger_schema(current: dict) -> dict:
    return {
        **_host_schema(current.get(CONF_LOGGER_HOST)),
        **{
            vol.Optional(key, default=current.get(key, default)): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=minimum,
                        max=maximum,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            )
            for key, minimum, maximum, default in _LOGGER_NUMBERS
        },
    }


def _has_meter(entry: ConfigEntry) -> bool:
    return CONF_TOPIC in entry.data


def _sources(entry: ConfigEntry) -> list[str]:
    """Helper sources whose entities exist for this entry's mode."""
    meter, logger = _has_meter(entry), bool(entry.options.get(CONF_LOGGER_HOST))
    needs = {
        "import": meter,
        "export": meter,
        "solar": logger,
        "household": meter and logger,
    }
    return [key for key in SOURCES if needs[key]]


def _multi_select(key: str, options, default) -> dict:
    return {
        vol.Optional(key, default=list(default)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(options),
                multiple=True,
                translation_key=key,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
    }


def _valid_seconds(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 1 <= value <= 86400
    )


class SnifferConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the passive meter, the read-only logger, or both."""

    VERSION = 1

    def __init__(self) -> None:
        self._mode = "meter"
        self._meter: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose what to monitor; MQTT is only needed for the meter."""
        if user_input is not None:
            self._mode = user_input[CONF_MODE]
            if self._mode == "logger":
                return await self.async_step_logger()
            if not mqtt.mqtt_config_entry_enabled(self.hass):
                return self.async_abort(reason="mqtt_required")
            return await self.async_step_meter()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODE, default="both"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(MODES),
                            translation_key=CONF_MODE,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the exact topic, availability timeout and update interval."""
        if not mqtt.mqtt_config_entry_enabled(self.hass):
            return self.async_abort(reason="mqtt_required")
        errors = {}
        if user_input is not None:
            user_input = dict(user_input)
            user_input.setdefault(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            topic = user_input[CONF_TOPIC]
            try:
                mqtt.valid_publish_topic(topic)  # Exact topic: wildcards are unsafe.
            except (vol.Invalid, ValueError, TypeError):
                errors[CONF_TOPIC] = "invalid_topic"
            if not _valid_seconds(user_input[CONF_TIMEOUT]):
                errors[CONF_TIMEOUT] = "invalid_timeout"
            if not _valid_seconds(user_input[CONF_UPDATE_INTERVAL]):
                errors[CONF_UPDATE_INTERVAL] = "invalid_update_interval"
            if not errors:
                await self.async_set_unique_id(topic)
                self._abort_if_unique_id_configured()
                if self._mode == "both":
                    self._meter = user_input
                    return await self.async_step_logger()
                return self.async_create_entry(title=METER_TITLE, data=user_input)
        defaults = user_input or {}
        return self.async_show_form(
            step_id="meter",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TOPIC,
                        default=defaults.get(CONF_TOPIC, DEFAULT_TOPIC),
                    ): str,
                    **_seconds_schema(defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
                    **_seconds_schema(
                        defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                        CONF_UPDATE_INTERVAL,
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_logger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the logger address; settings live in options for Configure."""
        errors = {}
        if user_input is not None:
            logger = _logger_options(user_input, {}, errors)
            if not logger:
                errors[CONF_LOGGER_HOST] = "logger_required"
            if not errors:
                if not self._meter:
                    await self.async_set_unique_id(
                        f"logger_{logger[CONF_LOGGER_HOST].lower()}"
                    )
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=METER_TITLE if self._meter else LOGGER_TITLE,
                    data=self._meter,
                    options=logger,
                )
        return self.async_show_form(
            step_id="logger",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_logger_schema({})), user_input
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SnifferOptionsFlow:
        """Return a modern options flow without assigning config_entry."""
        return SnifferOptionsFlow()


class SnifferOptionsFlow(OptionsFlow):
    """Configure the meter, the optional logger, and one-time energy helpers."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        menu = ["logger", "utility_meters"]
        if _has_meter(self.config_entry):
            menu.insert(0, "meter")
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self, changes: dict, keep_logger: bool = True) -> FlowResult:
        options = {
            key: value
            for key, value in self.config_entry.options.items()
            if keep_logger or not key.startswith("logger_")
        }
        options.update(changes)
        return self.async_create_entry(title="", data=options)

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Availability, publishing cadence and grid power direction."""
        errors = {}
        default_sign = self.config_entry.options.get(
            CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN
        )
        default_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        if user_input is not None:
            interval = user_input.get(CONF_UPDATE_INTERVAL, default_interval)
            if not _valid_seconds(interval):
                errors[CONF_UPDATE_INTERVAL] = "invalid_update_interval"
            sign = user_input.get(CONF_GRID_IMPORT_SIGN, default_sign)
            if not _valid_seconds(user_input[CONF_TIMEOUT]):
                errors[CONF_TIMEOUT] = "invalid_timeout"
            if sign not in ("positive", "negative"):
                errors[CONF_GRID_IMPORT_SIGN] = "invalid_direction"
            if not errors:
                return self._save(
                    {
                        CONF_TIMEOUT: user_input[CONF_TIMEOUT],
                        CONF_UPDATE_INTERVAL: interval,
                        CONF_GRID_IMPORT_SIGN: sign,
                        CONF_METER_REVERSED: bool(
                            user_input.get(CONF_METER_REVERSED, False)
                        ),
                    }
                )
        default = self.config_entry.options.get(
            CONF_TIMEOUT, self.config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        )
        schema = {
            **_seconds_schema(default),
            **_seconds_schema(default_interval, CONF_UPDATE_INTERVAL),
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
                CONF_METER_REVERSED,
                default=self.config_entry.options.get(CONF_METER_REVERSED, False),
            ): selector.BooleanSelector(),
        }
        return self.async_show_form(
            step_id="meter",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), user_input
            ),
            errors=errors,
        )

    async def async_step_logger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional read-only logger; an empty host disables polling."""
        errors = {}
        current = self.config_entry.options
        if user_input is not None:
            logger = _logger_options(user_input, current, errors)
            if not logger and not _has_meter(self.config_entry):
                errors[CONF_LOGGER_HOST] = "logger_required"
            if not errors:
                return self._save(logger, keep_logger=False)
        schema = _logger_schema(current)
        return self.async_show_form(
            step_id="logger",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), user_input
            ),
            errors=errors,
        )

    async def async_step_utility_meters(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create missing helpers once; nothing is stored for future startups."""
        errors = {}
        available = _sources(self.config_entry)
        default_sources = [
            key for key in DEFAULT_SOURCES if key in available
        ] or available[:1]
        if user_input is not None:
            cycles = user_input.get(CONF_UTILITY_CYCLES, DEFAULT_CYCLES)
            sources = user_input.get(CONF_UTILITY_SOURCES, default_sources)
            if not set(cycles) <= set(CYCLES) or not set(sources) <= set(available):
                errors["base"] = "invalid_helper_selection"
            else:
                try:
                    await async_create_utility_meters(
                        self.hass,
                        self.config_entry,
                        cycles=tuple(cycles),
                        source_keys=tuple(sources),
                    )
                except UtilityMeterSetupError as err:
                    errors["base"] = str(err)
                else:
                    return self._save({})
        return self.async_show_form(
            step_id="utility_meters",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        **_multi_select(CONF_UTILITY_CYCLES, CYCLES, DEFAULT_CYCLES),
                        **_multi_select(
                            CONF_UTILITY_SOURCES, available, default_sources
                        ),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )
