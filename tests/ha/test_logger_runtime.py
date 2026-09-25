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
    with patch.object(runtime, "clock", return_value=100):
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
