"""Passively expose an SDM630MCT observed through binary MQTT traffic."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_TIMEOUT, CONF_TOPIC, DEFAULT_TIMEOUT
from .runtime import SnifferRuntime

type SnifferConfigEntry = ConfigEntry[SnifferRuntime]

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> bool:
    """Set up one stream and forward native sensors."""
    runtime = entry.runtime_data = SnifferRuntime(
        hass,
        entry.data[CONF_TOPIC],
        entry.options.get(CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
    )
    try:
        await runtime.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        runtime.async_stop()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> None:
    """Apply changed options without retaining old stream state."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SnifferConfigEntry) -> bool:
    """Unload entities before releasing their runtime."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.async_stop()
        return True
    return False
