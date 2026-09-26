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
        assert '"last_success_age": null' in diagnostics

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass_storage[key]["data"] == {"solar": 5, "household": 7}
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


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


async def test_logger_only_setup(hass, mqtt_transport):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solis_sdm630_sniffer.const import DOMAIN

    subscribe, _ = mqtt_transport
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="solo",
        data={},
        options={"logger_host": "192.0.2.10"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        subscribe.assert_not_called()
        ids = {
            e.unique_id
            for e in er.async_entries_for_config_entry(er.async_get(hass), "solo")
        }
        assert "solo_inverter_solar_ac_power" in ids
        assert "solo_inverter_estimated_solar_energy" in ids
        assert (
            not {
                "solo_52",
                "solo_inverter_household_power",
                "solo_inverter_estimated_household_energy",
                "solo_inverter_balance_status",
            }
            & ids
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_continuous_polling_checkpoints_before_shutdown(
    runtime, hass, hass_storage, freezer
):
    """A crash must not lose all energy accumulated during healthy polling."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.solis_sdm630_sniffer.const import DOMAIN

    async def read(address, count):
        if address == 33000:
            return (0x3306, 15, 27, 1)
        if address == 33147:
            return (0, 0, 0, 0, 0, 1000)
        return (0,) * count

    client = AsyncMock()
    client.read.side_effect = read
    runtime._schedule = lambda delay: None
    await runtime.async_start()
    start = dt_util.utcnow()
    runtime.clock = lambda: (dt_util.utcnow() - start).total_seconds()
    key = f"{DOMAIN}.test-entry.energy"
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock()
        try:
            for seconds in (0, 30, 60, 90, 120, 150):
                freezer.move_to(start + timedelta(seconds=seconds))
                await runtime.async_poll()
                async_fire_time_changed(hass, dt_util.utcnow())
                await hass.async_block_till_done()
                if seconds == 90:
                    assert key in hass_storage, "No checkpoint during healthy polling"
                    first = hass_storage[key]["data"]["solar"]
                    assert first > 0
            assert hass_storage[key]["data"]["solar"] > first
        finally:
            await runtime.async_stop()


async def test_expiry_notifies_for_each_register_deadline(runtime, hass, freezer):
    """Later register groups must expire even while the next poll is stalled."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    runtime._running = True
    start = dt_util.utcnow()
    runtime.clock = lambda: (dt_util.utcnow() - start).total_seconds()
    stamp = runtime.clock()
    runtime.values = {"model": "0x3306", "temperature": 25, "frequency": 50}
    runtime.updated_at = {
        "model": stamp,
        "temperature": stamp + 10,
        "frequency": stamp + 20,
    }
    observed = []
    runtime.async_add_listener(lambda: observed.append(set(runtime.values)))
    try:
        freezer.move_to(start + timedelta(seconds=65))
        runtime._expire(None)  # First group's deadline has fired.
        assert observed == [{"temperature", "frequency"}]
        freezer.move_to(start + timedelta(seconds=75))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert observed[-1] == {"frequency"}
        freezer.move_to(start + timedelta(seconds=85))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert observed[-1] == set()
        assert not runtime.updated_at
        assert runtime._cancel_expiry is None
    finally:
        await runtime.async_stop()


async def test_expiry_removes_derived_timestamps_and_stop_cancels_timer(runtime):
    """Invalidated estimates must not leave a deadline that fires forever."""
    runtime._running = True
    runtime.clock = lambda: 65
    runtime.values = {
        "model": "0x3306",
        "ac_grid_power": 1000,
        "solar_ac_power": 1000,
        "estimated_solar_energy": 1,
    }
    runtime.updated_at = {key: 10 for key in runtime.values}
    runtime.updated_at["model"] = 0
    runtime._expire(None)
    assert set(runtime.values) == {"ac_grid_power"}
    assert runtime.updated_at == {"ac_grid_power": 10}
    assert runtime._cancel_expiry is not None
    await runtime.async_stop()
    assert runtime._cancel_expiry is None


async def test_sustained_failures_raise_and_clear_repair(runtime, hass):
    from homeassistant.helpers import issue_registry as ir

    issue_id = "logger_unreachable_test-entry"
    registry = ir.async_get(hass)
    client = AsyncMock()
    client.read.side_effect = lambda address, count: (
        (0x3306, 15, 27, 1) if address == 33000 else (0,) * count
    )
    healthy = AsyncMock(return_value=client)
    runtime._running = True
    runtime._schedule = lambda delay: None
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aexit__ = AsyncMock()
        reader.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError)
        await runtime.async_poll()
        assert registry.async_get_issue("solis_sdm630_sniffer", issue_id) is None
        for _ in range(4):
            await runtime.async_poll()
        issue = registry.async_get_issue("solis_sdm630_sniffer", issue_id)
        assert issue.severity == ir.IssueSeverity.ERROR
        assert not issue.is_fixable
        assert "example.test" not in str(issue.translation_placeholders)

        reader.return_value.__aenter__ = healthy
        await runtime.async_poll()
        assert runtime.failures == 0
        assert registry.async_get_issue("solis_sdm630_sniffer", issue_id) is None

        reader.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError)
        for _ in range(5):
            await runtime.async_poll()
    assert registry.async_get_issue("solis_sdm630_sniffer", issue_id)
    await runtime.async_stop()
    assert registry.async_get_issue("solis_sdm630_sniffer", issue_id) is None


async def test_unsupported_model_is_reported_immediately(runtime, hass):
    from homeassistant.helpers import issue_registry as ir

    client = AsyncMock()
    client.read.side_effect = lambda address, count: (0x1234,) + (0,) * (count - 1)
    runtime._running = True
    runtime._schedule = lambda delay: None
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aenter__ = AsyncMock(return_value=client)
        reader.return_value.__aexit__ = AsyncMock(return_value=False)
        await runtime.async_poll()
    assert runtime.last_error == "UnsupportedModel"
    issue = ir.async_get(hass).async_get_issue(
        "solis_sdm630_sniffer", "logger_unreachable_test-entry"
    )
    assert issue.translation_key == "unsupported_model"
    await runtime.async_stop()


@pytest.mark.parametrize(
    ("enter", "expected"),
    [
        ((0x3306,), None),
        ((0x1234,), "unsupported_model"),
        (TimeoutError(), "cannot_connect"),
    ],
)
async def test_probe_logger(enter, expected):
    from custom_components.solis_sdm630_sniffer.logger_runtime import (
        async_probe_logger,
    )

    client = AsyncMock()
    client.read.return_value = enter
    with patch(
        "custom_components.solis_sdm630_sniffer.logger_runtime.ModbusReader"
    ) as reader:
        reader.return_value.__aexit__ = AsyncMock(return_value=False)
        reader.return_value.__aenter__ = AsyncMock(
            side_effect=enter if isinstance(enter, Exception) else None,
            return_value=client,
        )
        assert await async_probe_logger("192.0.2.1", 502, 1) == expected
    if expected != "cannot_connect":
        client.read.assert_awaited_once_with(33000, 1)
