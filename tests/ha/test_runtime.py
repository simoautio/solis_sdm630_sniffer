"""Exercise binary subscription, freshness, entities and lifecycle using HA."""

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solis_sdm630_sniffer import async_setup_entry, async_unload_entry
from custom_components.solis_sdm630_sniffer.const import DOMAIN
from custom_components.solis_sdm630_sniffer.protocol import crc16
from custom_components.solis_sdm630_sniffer.runtime import SnifferRuntime
from custom_components.solis_sdm630_sniffer.sensor import DESCRIPTIONS, SnifferSensor


def frame(body):
    return body + crc16(body).to_bytes(2, "little")


def transaction(address=0, value=230.5):
    return frame(struct.pack(">BBHH", 1, 4, address, 2)) + frame(
        b"\x01\x04\x04" + struct.pack(">f", value)
    )


def message(payload, retain=False):
    return SimpleNamespace(payload=payload, retain=retain)


@pytest.fixture
def entry(hass):
    result = MockConfigEntry(
        domain=DOMAIN, data={"topic": "solis/rs485/raw", "timeout": 60}
    )
    result.add_to_hass(hass)
    return result


async def test_binary_sensor_and_cleanup(hass, entry, mqtt_transport):
    runtime = SnifferRuntime(hass, "solis/rs485/raw", 60)
    entry.runtime_data = runtime
    sensor = SnifferSensor(entry, DESCRIPTIONS[0])
    await runtime.async_start()
    subscribe, connection = mqtt_transport
    subscribe.assert_awaited_once_with(
        hass, "solis/rs485/raw", runtime.async_message_received, qos=0, encoding=None
    )
    assert not sensor.available
    runtime.async_message_received(message(transaction()[:6]))
    assert not sensor.available
    runtime.async_message_received(message(transaction()[6:]))
    assert sensor.available
    assert sensor.native_value == 230.5
    assert sensor.native_unit_of_measurement == "V"
    assert sensor.device_class == "voltage"
    assert sensor.state_class == "measurement"
    runtime.async_stop()
    runtime.async_stop()
    subscribe.return_value.assert_called_once()
    connection.return_value.assert_called_once()


async def test_retained_invalid_and_timeout(hass, mqtt_transport):
    now = [0.0]
    runtime = SnifferRuntime(hass, "test", 60, clock=lambda: now[0])
    await runtime.async_start()
    try:
        runtime.async_message_received(message(transaction(), retain=True))
        runtime.async_message_received(message("not binary"))
        assert not runtime.values
        runtime.async_message_received(message(transaction()))
        assert runtime.is_available(0)
        now[0] = 40
        runtime.async_message_received(message(transaction(6, 3)))
        now[0] = 61
        runtime.async_check_expiry()
        assert not runtime.is_available(0)
        assert runtime.is_available(6)
        now[0] = 101
        runtime.async_check_expiry()
        assert not runtime.is_available(6)
        runtime.async_message_received(message(transaction()))
        assert runtime.is_available(0)
    finally:
        runtime.async_stop()


async def test_disconnect_and_sensor_listener(hass, entry, mqtt_transport):
    runtime = SnifferRuntime(hass, "test", 60)
    entry.runtime_data = runtime
    sensor = SnifferSensor(entry, DESCRIPTIONS[0])
    sensor.hass = hass
    sensor.entity_id = "sensor.test_voltage"
    await runtime.async_start()
    await sensor.async_added_to_hass()
    runtime.async_message_received(message(transaction()))
    assert hass.states.get(sensor.entity_id).state == "230.5"
    runtime.async_message_received(message(transaction()[:10]))
    runtime.async_connection_changed(False)
    assert not sensor.available
    assert runtime.parser.buffer_size == 0
    runtime.async_connection_changed(True)
    runtime.async_message_received(message(transaction()[8:]))
    assert not sensor.available
    runtime.async_message_received(message(transaction()))
    assert sensor.available
    await sensor.async_remove(force_remove=True)
    assert not runtime.listeners
    runtime.async_stop()


async def test_invalid_values_and_energy(hass, entry, mqtt_transport):
    runtime = SnifferRuntime(hass, "test", 60)
    entry.runtime_data = runtime
    await runtime.async_start()
    try:
        runtime.async_message_received(message(transaction(72, -1)))
        assert not runtime.is_available(72)
        runtime.async_message_received(message(transaction(72, 100)))
        sensor = SnifferSensor(entry, next(d for d in DESCRIPTIONS if d.address == 72))
        assert sensor.native_value == 100
        assert sensor.device_class == "energy"
        assert sensor.state_class == "total_increasing"
        assert sensor.native_unit_of_measurement == "kWh"
        runtime.async_message_received(message(transaction(52, -1200)))
        assert runtime.values[52] == -1200
    finally:
        runtime.async_stop()


async def test_lifecycle_and_setup_failure(hass, entry, mqtt_transport):
    with (
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
    ):
        assert await async_setup_entry(hass, entry)
        assert await async_unload_entry(hass, entry)
    mqtt_transport[0].return_value.assert_called_once()
    mqtt_transport[0].return_value.reset_mock()
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=RuntimeError("setup failed"),
    ):
        with pytest.raises(RuntimeError, match="setup failed"):
            await async_setup_entry(hass, entry)
    mqtt_transport[0].return_value.assert_called_once()


async def test_timer_schedules_and_notifies(hass, mqtt_transport):
    now = [0.0]
    runtime = SnifferRuntime(hass, "test", 60, clock=lambda: now[0])
    listener = Mock()
    remove = runtime.async_add_listener(listener)
    with patch(
        "custom_components.solis_sdm630_sniffer.runtime.async_call_later"
    ) as schedule:
        await runtime.async_start()
        runtime.async_message_received(message(transaction()))
        expiry = next(call for call in schedule.call_args_list if call.args[1] == 60)
        now[0] = 60
        expiry.args[2](None)
        assert not runtime.is_available(0)
        assert listener.call_count == 2
        remove()
        runtime.async_stop()


async def test_options_update_requests_reload(hass, entry, mqtt_transport):
    with (
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch.object(hass.config_entries, "async_reload", return_value=True) as reload,
    ):
        await async_setup_entry(hass, entry)
        try:
            hass.config_entries.async_update_entry(entry, options={"timeout": 120})
            await hass.async_block_till_done()
            reload.assert_awaited_once_with(entry.entry_id)
        finally:
            entry.runtime_data.async_stop()


async def test_subscribe_failure_removes_connection_listener(hass, mqtt_transport):
    mqtt_transport[0].side_effect = RuntimeError("subscribe failed")
    runtime = SnifferRuntime(hass, "test", 60)
    with pytest.raises(RuntimeError, match="subscribe failed"):
        await runtime.async_start()
    mqtt_transport[1].return_value.assert_called_once()
    assert not runtime.is_available(0)


async def test_interval_batches_latest_without_availability_leaks(
    hass, entry, mqtt_transport
):
    now = [0.0]
    runtime = SnifferRuntime(hass, "test", 60, clock=lambda: now[0])
    entry.runtime_data = runtime
    sensor = SnifferSensor(entry, DESCRIPTIONS[0])
    sensor.hass = hass
    sensor.entity_id = "sensor.interval_voltage"
    await runtime.async_start()
    await sensor.async_added_to_hass()
    try:
        runtime.async_message_received(message(transaction(0, 230)))
        assert hass.states.get(sensor.entity_id).state == "230.0"
        now[0] = 1
        runtime.async_message_received(message(transaction(0, 231)))
        assert sensor.native_value == 230
        # A different sensor's first reading must not flush pending voltage.
        runtime.async_message_received(message(transaction(6, 3)))
        assert hass.states.get(sensor.entity_id).state == "230.0"
        now[0] = 29
        runtime.async_message_received(message(transaction(0, 232)))
        assert sensor.native_value == 230
        now[0] = 30
        runtime.async_publish_values()
        assert hass.states.get(sensor.entity_id).state == "232.0"
        unchanged = hass.states.get(sensor.entity_id)
        now[0] = 60
        runtime.async_publish_values()
        assert hass.states.get(sensor.entity_id) is unchanged
        now[0] = 62
        runtime.async_check_expiry()
        assert sensor.available  # Incoming samples, not publications, set freshness.
        now[0] = 89
        runtime.async_check_expiry()
        assert hass.states.get(sensor.entity_id).state == "unavailable"
        runtime.async_message_received(message(transaction(0, 233)))
        assert hass.states.get(sensor.entity_id).state == "233.0"
        runtime.async_connection_changed(False)
        assert hass.states.get(sensor.entity_id).state == "unavailable"
    finally:
        await sensor.async_remove(force_remove=True)
        runtime.async_stop()


async def test_interval_timer_flushes_and_cleans_up(hass, mqtt_transport):
    now = [0.0]
    runtime = SnifferRuntime(hass, "test", 60, update_interval=10, clock=lambda: now[0])
    with patch(
        "custom_components.solis_sdm630_sniffer.runtime.async_call_later"
    ) as schedule:
        await runtime.async_start()
        runtime.async_message_received(message(transaction(72, 100)))
        publication = next(
            call for call in schedule.call_args_list if call.args[1] == 10
        )
        now[0] = 1
        runtime.async_message_received(message(transaction(72, 105)))
        assert runtime.values[72] == 100
        now[0] = 10
        publication.args[2](None)
        assert runtime.values[72] == 105
        runtime.async_stop()
        now[0] = 20
        publication.args[2](None)
        assert not runtime.is_available(72)
        assert runtime._cancel_publish_timer is None


@pytest.mark.parametrize(
    "data_interval, option_interval, expected",
    [(None, None, 30), (15, None, 15), (15, 1, 1)],
)
async def test_setup_uses_interval(
    hass, entry, mqtt_transport, data_interval, option_interval, expected
):
    if data_interval is not None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "update_interval": data_interval}
        )
    if option_interval is not None:
        hass.config_entries.async_update_entry(
            entry, options={"update_interval": option_interval}
        )
    with patch.object(
        hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
    ):
        await async_setup_entry(hass, entry)
    try:
        assert entry.runtime_data.update_interval == expected
    finally:
        entry.runtime_data.async_stop()


async def test_real_timer_updates_grid_power_and_stops_on_disconnect(
    hass, entry, mqtt_transport, freezer
):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.solis_sdm630_sniffer.sensor import GRID_DESCRIPTIONS

    now = [0.0]
    runtime = entry.runtime_data = SnifferRuntime(
        hass, "test", 60, update_interval=10, clock=lambda: now[0]
    )
    sensors = [SnifferSensor(entry, description) for description in GRID_DESCRIPTIONS]
    await runtime.async_start()
    try:
        runtime.async_message_received(message(transaction(52, 500)))
        now[0] = 1
        runtime.async_message_received(message(transaction(52, -700)))
        assert tuple(sensor.native_value for sensor in sensors) == (500, 0)
        now[0] = 10
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert tuple(sensor.native_value for sensor in sensors) == (0, 700)
        now[0] = 11
        runtime.async_message_received(message(transaction(52, 900)))
        runtime.async_connection_changed(False)
        now[0] = 20
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert tuple(sensor.native_value for sensor in sensors) == (0, 700)
        assert all(not sensor.available for sensor in sensors)
        runtime.async_connection_changed(True)
        runtime.async_message_received(message(transaction(52, 1200)))
        assert tuple(sensor.native_value for sensor in sensors) == (1200, 0)
    finally:
        runtime.async_stop()
