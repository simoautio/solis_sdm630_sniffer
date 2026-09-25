"""Passively expose an SDM630MCT observed through binary MQTT traffic."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LOGGER_HOST,
    CONF_TIMEOUT,
    CONF_TOPIC,
    CONF_UPDATE_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
)
from .logger_runtime import LoggerRuntime, energy_store
from .runtime import SnifferRuntime

type SnifferConfigEntry = ConfigEntry[SnifferRuntime]

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> bool:
    """Set up one stream and forward native sensors."""
    runtime = entry.runtime_data = SnifferRuntime(
        hass,
        entry.data[CONF_TOPIC],
        entry.options.get(CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        update_interval=entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ),
    )
    try:
        await runtime.async_start()
        if entry.options.get(CONF_LOGGER_HOST):
            runtime.logger = LoggerRuntime(hass, runtime, entry.entry_id, entry.options)
            await runtime.logger.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await _async_stop(runtime)
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> None:
    """Apply changed options without retaining old stream state."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> bool:
    """Unload entities before releasing their runtime."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await _async_stop(entry.runtime_data)
        return True
    return False


async def async_remove_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> None:
    """Delete persisted estimates; Utility Meter helpers are left untouched."""
    await energy_store(hass, entry.entry_id).async_remove()


async def _async_stop(runtime: SnifferRuntime) -> None:
    """Stop the logger first: it listens to the meter runtime."""
    if runtime.logger:
        await runtime.logger.async_stop()
        runtime.logger = None
    runtime.async_stop()
