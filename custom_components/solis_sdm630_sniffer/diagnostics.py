"""Privacy-conscious stream diagnostics; no raw payloads or topic names."""

from homeassistant.core import HomeAssistant

from . import SnifferConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SnifferConfigEntry,
) -> dict:
    """Return counters and sample ages, never raw MQTT payload history."""
    runtime = entry.runtime_data
    now = runtime.clock()
    pending = runtime.parser.pending
    last_request = runtime.parser.last_request
    return {
        "topic": "**REDACTED**",
        "traffic_status": runtime.traffic_status,
        "timeout": runtime.timeout,
        "update_interval": runtime.update_interval,
        "last_response_age": (
            now - runtime.last_response_at
            if runtime.last_response_at is not None
            else None
        ),
        "register_ages": {
            str(address): now - stamp for address, stamp in runtime.updated_at.items()
        },
        "parser": {
            "buffer_size": runtime.parser.buffer_size,
            "counters": dict(runtime.parser.counters),
            "last_request": (
                {
                    "start": last_request.start,
                    "count": last_request.count,
                    "age": now - last_request.received_at,
                }
                if last_request
                else None
            ),
            "pending_request": (
                {
                    "start": pending.start,
                    "count": pending.count,
                    "age": now - pending.received_at,
                }
                if pending
                else None
            ),
        },
    }
