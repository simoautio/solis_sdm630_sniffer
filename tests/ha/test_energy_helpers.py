"""Grid direction, optional helper creation, and preserved meter identity."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solis_sdm630_sniffer.const import DOMAIN
from custom_components.solis_sdm630_sniffer.runtime import SnifferRuntime
from custom_components.solis_sdm630_sniffer.sensor import (
    DESCRIPTIONS,
    GRID_DESCRIPTIONS,
    SnifferSensor,
)
from custom_components.solis_sdm630_sniffer.utility_meters import (
    UtilityMeterSetupError,
    async_create_utility_meters,
)


async def open_options(hass, entry, step):
    """Open Configure and choose one menu page."""
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] == FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": step}
    )


@pytest.fixture
def energy_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Solis SDM630 Sniffer",
        data={"topic": "test", "timeout": 60},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize(
    "sign, expected", [("positive", (500, 0)), ("negative", (0, 500))]
)
async def test_native_grid_power(hass, energy_entry, mqtt_transport, sign, expected):
    hass.config_entries.async_update_entry(
        energy_entry, options={"grid_import_sign": sign}
    )
    runtime = energy_entry.runtime_data = SnifferRuntime(hass, "test", 60)
    await runtime.async_start()
    try:
        sensors = [SnifferSensor(energy_entry, item) for item in GRID_DESCRIPTIONS]
        assert all(
            sensor.native_value is None and not sensor.available for sensor in sensors
        )
        runtime.values[52] = 500
        runtime.updated_at[52] = runtime.last_response_at = runtime.clock()
        assert tuple(sensor.native_value for sensor in sensors) == expected
        assert all(sensor.available for sensor in sensors)
        assert all(sensor.native_unit_of_measurement == "W" for sensor in sensors)
        assert all(
            sensor.device_class == "power" and sensor.state_class == "measurement"
            for sensor in sensors
        )
        assert {sensor.unique_id for sensor in sensors} == {
            f"{energy_entry.entry_id}_grid_import_power",
            f"{energy_entry.entry_id}_grid_export_power",
        }
        runtime.async_connection_changed(False)
        assert all(not sensor.available for sensor in sensors)
        meter = SnifferSensor(
            energy_entry, next(d for d in DESCRIPTIONS if d.address == 72)
        )
        assert meter.unique_id == f"{energy_entry.entry_id}_72"
        runtime.values[72] = 1200
        assert meter.native_value == 1200  # Sign setting never swaps meter counters.
    finally:
        runtime.async_stop()


def register_sources(hass, entry):
    registry = er.async_get(hass)
    return [
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{address}",
            config_entry=entry,
            suggested_object_id=f"custom_meter_{address}",
        )
        for address in (72, 74)
    ]


async def test_selected_cycles_and_estimated_sources(hass, energy_entry):
    register_sources(hass, energy_entry)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{energy_entry.entry_id}_inverter_estimated_solar_energy",
        config_entry=energy_entry,
    )
    with patch.object(hass.config_entries, "async_setup", return_value=True):
        assert (
            await async_create_utility_meters(
                hass,
                energy_entry,
                cycles=["quarter-hourly", "hourly"],
                source_keys=["import", "solar"],
            )
            == 4
        )
        await hass.async_block_till_done()
        assert (
            await async_create_utility_meters(
                hass,
                energy_entry,
                cycles=["quarter-hourly", "hourly"],
                source_keys=["import", "solar"],
            )
            == 0
        )
    assert {
        entry.options["cycle"]
        for entry in hass.config_entries.async_entries("utility_meter")
    } == {"quarter-hourly", "hourly"}


async def test_create_real_helpers_and_idempotence(hass, energy_entry):
    sources = register_sources(hass, energy_entry)
    assert await async_setup_component(hass, "utility_meter", {})
    await hass.async_start()
    result = await async_create_utility_meters(hass, energy_entry)
    await hass.async_block_till_done()
    assert result == 6
    entries = hass.config_entries.async_entries("utility_meter")
    assert len(entries) == 6
    assert {(entry.options["source"], entry.options["cycle"]) for entry in entries} == {
        (source.entity_id, cycle)
        for source in sources
        for cycle in ("daily", "monthly", "yearly")
    }
    assert all(entry.options["periodically_resetting"] is False for entry in entries)
    assert all(entry.options["net_consumption"] is False for entry in entries)
    assert all(entry.options["delta_values"] is False for entry in entries)
    attributes = {
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    }
    hass.states.async_set(sources[0].entity_id, "100", attributes)
    await hass.async_block_till_done()
    hass.states.async_set(sources[0].entity_id, "101.5", attributes)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    import_entries = [
        entry for entry in entries if entry.options["source"] == sources[0].entity_id
    ]
    for entry in import_entries:
        entity = er.async_entries_for_config_entry(registry, entry.entry_id)[0]
        assert float(hass.states.get(entity.entity_id).state) == 1.5
    assert await async_create_utility_meters(hass, energy_entry) == 0
    assert len(hass.config_entries.async_entries("utility_meter")) == 6
    # Persisted source UUIDs are recognized after the native helper handles a rename.
    registry.async_update_entity(
        sources[0].entity_id, new_entity_id="sensor.renamed_import"
    )
    await hass.async_block_till_done()
    assert await async_create_utility_meters(hass, energy_entry) == 0
    assert len(hass.config_entries.async_entries("utility_meter")) == 6


async def test_validate_both_sources_before_creating(hass, energy_entry):
    with pytest.raises(UtilityMeterSetupError, match="sources_not_ready"):
        await async_create_utility_meters(hass, energy_entry)
    assert not hass.config_entries.async_entries("utility_meter")
    sources = register_sources(hass, energy_entry)
    er.async_get(hass).async_update_entity(
        sources[1].entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    with pytest.raises(UtilityMeterSetupError, match="sources_not_ready"):
        await async_create_utility_meters(hass, energy_entry)
    assert not hass.config_entries.async_entries("utility_meter")


async def test_options_sign_and_one_time_helper_action(hass, energy_entry):
    result = await open_options(hass, energy_entry, "meter")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"timeout": 90, "grid_import_sign": "negative"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert energy_entry.options == {
        "timeout": 90,
        "grid_import_sign": "negative",
        "update_interval": 30,
        "meter_reversed": False,
    }
    result = await open_options(hass, energy_entry, "utility_meters")
    with patch(
        "custom_components.solis_sdm630_sniffer.config_flow.async_create_utility_meters",
        return_value=2,
    ) as create:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "utility_meter_cycles": ["hourly"],
                "utility_meter_sources": ["import", "export"],
            },
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        create.assert_awaited_once_with(
            hass, energy_entry, cycles=("hourly",), source_keys=("import", "export")
        )
    # The action is not persisted: reloads never recreate deleted helpers.
    assert energy_entry.options == {
        "timeout": 90,
        "grid_import_sign": "negative",
        "update_interval": 30,
        "meter_reversed": False,
    }


async def test_options_helper_error_is_retryable(hass, energy_entry):
    result = await open_options(hass, energy_entry, "utility_meters")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "sources_not_ready"}
    assert energy_entry.options == {}


async def test_concurrent_requests_do_not_duplicate(hass, energy_entry):
    import asyncio

    register_sources(hass, energy_entry)
    with patch.object(hass.config_entries, "async_setup", return_value=True):
        counts = await asyncio.gather(
            async_create_utility_meters(hass, energy_entry),
            async_create_utility_meters(hass, energy_entry),
        )
        await hass.async_block_till_done()
    assert sorted(counts) == [0, 6]
    assert len(hass.config_entries.async_entries("utility_meter")) == 6


async def test_partial_creation_failure_can_be_retried(hass, energy_entry):
    register_sources(hass, energy_entry)
    original_init = hass.config_entries.flow.async_init
    calls = 0

    async def fail_after_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return {"type": FlowResultType.ABORT, "reason": "test_failure"}
        return await original_init(*args, **kwargs)

    with (
        patch.object(hass.config_entries, "async_setup", return_value=True),
        patch.object(
            hass.config_entries.flow, "async_init", side_effect=fail_after_first
        ),
    ):
        with pytest.raises(UtilityMeterSetupError, match="utility_meters_failed"):
            await async_create_utility_meters(hass, energy_entry)
        await hass.async_block_till_done()
    entries = hass.config_entries.async_entries("utility_meter")
    assert len(entries) == 1
    first_id = entries[0].entry_id
    with patch.object(hass.config_entries, "async_setup", return_value=True):
        assert await async_create_utility_meters(hass, energy_entry) == 5
        await hass.async_block_till_done()
    entries = hass.config_entries.async_entries("utility_meter")
    assert len(entries) == 6
    assert first_id in {entry.entry_id for entry in entries}


async def test_reversed_meter_relabels_counters_and_helper_sources(hass, energy_entry):
    hass.config_entries.async_update_entry(
        energy_entry, options={"meter_reversed": True}
    )
    energy_entry.runtime_data = SnifferRuntime(hass, "test", 60)
    by_address = {d.address: d for d in DESCRIPTIONS}
    imported = SnifferSensor(energy_entry, by_address[72])
    phase = SnifferSensor(energy_entry, by_address[352])
    # Same unique ID and value source; only the label follows physical direction.
    assert imported.unique_id == f"{energy_entry.entry_id}_72"
    assert imported.name == "Export energy"
    assert phase.name == "L1 import energy"
    assert SnifferSensor(energy_entry, by_address[52]).name == "Total active power"
    energy_entry.runtime_data.values[72] = 327
    assert imported.native_value == 327

    sources = register_sources(hass, energy_entry)
    with patch.object(
        hass.config_entries.flow, "async_init", return_value={"type": "create_entry"}
    ) as create:
        assert (
            await async_create_utility_meters(
                hass, energy_entry, cycles=("daily",), source_keys=("import",)
            )
            == 1
        )
    # "import" helpers track the meter's physical import: register 74.
    assert create.call_args.kwargs["data"]["source"] == sources[1].entity_id
