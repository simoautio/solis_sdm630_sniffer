"""Explicit, idempotent creation of native Home Assistant Utility Meter helpers."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import CONF_METER_REVERSED, DOMAIN

_LOGGER = logging.getLogger(__name__)
_LOCK_KEY = f"{DOMAIN}.utility_meter_creation_lock"
CYCLES = ("quarter-hourly", "hourly", "daily", "monthly", "yearly")
DEFAULT_CYCLES = ("daily", "monthly", "yearly")
# Source key -> unique-id suffix. Estimated sources exist only with a logger.
SOURCES = {
    "import": "72",
    "export": "74",
    "solar": "inverter_estimated_solar_energy",
    "household": "inverter_estimated_household_energy",
}
DEFAULT_SOURCES = ("import", "export")


class UtilityMeterSetupError(HomeAssistantError):
    """A user-visible, retryable error during requested helper creation."""


async def async_create_utility_meters(
    hass: HomeAssistant,
    entry: ConfigEntry,
    cycles=DEFAULT_CYCLES,
    source_keys=DEFAULT_SOURCES,
) -> int:
    """Create missing helpers without altering existing counters or helper history.

    Use the built-in config flow so source tracking, persistence, calendar resets,
    and statistics remain owned by Utility Meter. This action is not run on startup.
    """
    lock = hass.data.setdefault(_LOCK_KEY, asyncio.Lock())
    async with lock:
        registry = er.async_get(hass)
        sources = []
        # Validate every source before creating any helpers. Never guess entity IDs:
        # users may have renamed them, or have multiple meter entries.
        reversed_meter = entry.options.get(CONF_METER_REVERSED, False)
        for direction in source_keys:
            suffix = SOURCES[direction]
            if reversed_meter and direction in ("import", "export"):
                suffix = SOURCES["export" if direction == "import" else "import"]
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
            )
            source = registry.async_get(entity_id) if entity_id else None
            if source is None or source.disabled_by is not None:
                raise UtilityMeterSetupError("sources_not_ready")
            sources.append((source, direction))

        created = 0
        for source, direction in sources:
            for cycle in cycles:
                options = {
                    "name": f"{entry.title} {direction} energy {cycle}",
                    "source": source.entity_id,
                    "cycle": cycle,
                    "offset": 0,
                    "tariffs": [],
                    "net_consumption": False,
                    "delta_values": False,
                    # Lifetime counters: recover deltas across temporary outages.
                    "periodically_resetting": False,
                    "always_available": False,
                }
                if any(
                    helper.options.get("source") in (source.entity_id, source.id)
                    and all(
                        helper.options.get(key, default) == options[key]
                        for key, default in (
                            ("cycle", None),
                            ("offset", 0),
                            ("tariffs", []),
                            ("net_consumption", False),
                            ("delta_values", False),
                            ("periodically_resetting", True),
                        )
                    )
                    for helper in hass.config_entries.async_entries("utility_meter")
                ):
                    continue
                try:
                    result = await hass.config_entries.flow.async_init(
                        "utility_meter", context={"source": SOURCE_USER}, data=options
                    )
                except HomeAssistantError as err:
                    _LOGGER.exception("Could not create requested utility meter")
                    raise UtilityMeterSetupError("utility_meters_failed") from err
                if result["type"] != FlowResultType.CREATE_ENTRY:
                    # Do not leave orphaned interactive flows behind on failure.
                    if "flow_id" in result and result["type"] != FlowResultType.ABORT:
                        hass.config_entries.flow.async_abort(result["flow_id"])
                    _LOGGER.error("Utility meter creation returned %s", result["type"])
                    raise UtilityMeterSetupError("utility_meters_failed")
                created += 1
        _LOGGER.debug(
            "Created %d utility meters; matching helpers were retained", created
        )
        return created
