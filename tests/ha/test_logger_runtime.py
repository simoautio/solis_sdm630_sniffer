"""Logger snapshots, source independence and energy restoration in real HA."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solis_sdm630_sniffer.logger_runtime import LoggerRuntime
from custom_components.solis_sdm630_sniffer.runtime import SnifferRuntime


@pytest.fixture
def runtime(hass):
    meter = SnifferRuntime(hass, "test", 60)
    meter._running = meter._connected = True
    return LoggerRuntime(hass, meter, "test-entry", {"logger_host": "example.test"})


def sample(runtime, stamp, ac=1000, backup=0):
    runtime.values = {"ac_grid_power": ac, "backup_power": backup}
    runtime.updated_at = {key: stamp for key in runtime.values}
    runtime.meter._latest_values[52] = 500
    runtime.meter.updated_at[52] = runtime.meter.last_response_at = stamp


async def test_aligned_power_and_stale_meter(runtime):
    runtime._running = True
    with (
        patch.object(runtime, "clock", return_value=100),
        patch.object(runtime.meter, "clock", return_value=100),
    ):
        sample(runtime, 100)
        runtime.update_combined(100)
        assert runtime.values["solar_ac_power"] == 1000
        assert runtime.values["household_power"] == 1500
        runtime.meter.updated_at[52] = 90
        runtime.update_combined(100)
        assert runtime.values["solar_ac_power"] == 1000
        assert "household_power" not in runtime.values
    await runtime.async_stop()


async def test_failure_breaks_integration_and_does_not_stop_meter(runtime):
    runtime._running = True
    runtime.meter.values[72] = 123
    runtime.solar.update(0, 1000)
    runtime.solar.update(30, 1000)
    before = runtime.solar.total
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError)
        await runtime.async_poll()
    assert runtime.values == {}
    assert runtime.solar.previous is None
    assert runtime.solar.total == before
    assert runtime.meter.values[72] == 123
    assert runtime.failures == 1
    await runtime.async_stop()


async def test_restore_never_bridges_restart(runtime):
    runtime.store.async_load = AsyncMock(return_value={"solar": 12, "household": 20})
    runtime._schedule = lambda delay: None
    await runtime.async_start()
    assert runtime.solar.total == 12
    assert runtime.household.total == 20
    assert runtime.solar.previous is None
    runtime.store.async_save = AsyncMock()
    await runtime.async_stop()
    runtime.store.async_save.assert_awaited_once_with({"solar": 12, "household": 20})


async def test_unsupported_group_keeps_other_readings(runtime):
    from custom_components.solis_sdm630_sniffer.modbus_tcp import UnsupportedRegisters

    async def read(address, count):
        if address == 33000:
            return (0x3306, 15, 27, 1)
        if address == 33029:
            raise UnsupportedRegisters()
        return (0,) * count

    client = AsyncMock()
    client.read.side_effect = read
    runtime._running = True
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock()
        await runtime.async_poll()
    assert "production_total" not in runtime.values
    assert runtime.values["production_today"] == 0
    assert runtime.values["ac_grid_power"] == 0
    await runtime.async_stop()


async def test_setup_independence_restore_and_redaction(
    hass, mqtt_transport, hass_storage
):
    import json
    from datetime import timedelta

    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_fire_time_changed,
    )

    from custom_components.solis_sdm630_sniffer.const import DOMAIN
    from custom_components.solis_sdm630_sniffer.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    key = f"{DOMAIN}.abc.energy"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"solar": 5, "household": 7},
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="abc",
        data={"topic": "test", "timeout": 60},
        options={"logger_host": "192.0.2.10"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError)
        assert await hass.config_entries.async_setup(entry.entry_id)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done(wait_background_tasks=True)

        meter = entry.runtime_data
        logger = meter.logger
        assert logger.failures >= 1
        assert logger.solar.total == 5 and logger.household.total == 7
        status = registry.async_get_entity_id("sensor", DOMAIN, "abc_inverter_status")
        assert hass.states.get(status).state == "unavailable"

        # A logger outage never affects meter availability.
        meter._latest_values[52] = 500
        meter.updated_at[52] = meter.last_response_at = meter.clock()
        meter.async_check_expiry()
        await hass.async_block_till_done()
        power = registry.async_get_entity_id("sensor", DOMAIN, "abc_52")
        assert hass.states.get(power).state == "500"

        diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
        assert "192.0.2.10" not in diagnostics
        assert '"last_error": "TimeoutError"' in diagnostics

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass_storage[key]["data"] == {"solar": 5, "household": 7}


async def test_no_logger_entities_without_host(hass, mqtt_transport):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solis_sdm630_sniffer.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN, entry_id="plain", data={"topic": "test", "timeout": 60}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.logger is None
    entities = er.async_entries_for_config_entry(er.async_get(hass), "plain")
    assert entities and not any("_inverter_" in e.unique_id for e in entities)
    assert await hass.config_entries.async_unload(entry.entry_id)
