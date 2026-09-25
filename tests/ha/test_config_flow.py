"""Configuration and diagnostic contract tests."""

import json
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solis_sdm630_sniffer.config_flow import SnifferConfigFlow
from custom_components.solis_sdm630_sniffer.const import DOMAIN
from custom_components.solis_sdm630_sniffer.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.solis_sdm630_sniffer.runtime import SnifferRuntime


async def test_defaults_and_create(hass, mqtt_transport):
    flow = SnifferConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow.handler = DOMAIN
    form = await flow.async_step_user()
    assert form["type"] == FlowResultType.FORM
    assert form["data_schema"]({}) == {
        "topic": "solis/rs485/raw",
        "timeout": 60,
        "update_interval": 30,
    }
    result = await flow.async_step_user({"topic": "solis/rs485/raw", "timeout": 60})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["topic"] == "solis/rs485/raw"


@pytest.mark.parametrize("topic", ["", "a/#", "a/+", "a\0b"])
async def test_invalid_topic(hass, mqtt_transport, topic):
    flow = SnifferConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user({"topic": topic, "timeout": 60})
    assert result["errors"] == {"topic": "invalid_topic"}


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
async def test_invalid_timeout(hass, mqtt_transport, timeout):
    flow = SnifferConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user({"topic": "test", "timeout": timeout})
    assert result["errors"] == {"timeout": "invalid_timeout"}


async def test_mqtt_required(hass):
    flow = SnifferConfigFlow()
    flow.hass = hass
    with patch(
        "homeassistant.components.mqtt.mqtt_config_entry_enabled", return_value=False
    ):
        assert (await flow.async_step_user())["reason"] == "mqtt_required"


async def test_duplicate_topic(hass, mqtt_transport):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="test", data={"topic": "test", "timeout": 60}
    )
    entry.add_to_hass(hass)
    # Use the real manager to translate the duplicate AbortFlow into a result.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"topic": "test", "timeout": 60}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options(hass, mqtt_transport):
    entry = MockConfigEntry(domain=DOMAIN, data={"topic": "test", "timeout": 60})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"timeout": 120}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "timeout": 120,
        "grid_import_sign": "positive",
        "update_interval": 30,
    }


async def test_diagnostics_redacted(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"topic": "secret/topic", "timeout": 60}
    )
    entry.runtime_data = SnifferRuntime(hass, "secret/topic", 60)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "secret/topic" not in json.dumps(diagnostics)
    assert diagnostics["parser"]["buffer_size"] == 0


@pytest.mark.parametrize(
    "interval", [0, -1, 86401, float("inf"), float("nan"), True, "30"]
)
async def test_invalid_update_interval(hass, mqtt_transport, interval):
    flow = SnifferConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user(
        {"topic": "test", "timeout": 60, "update_interval": interval}
    )
    assert result["errors"] == {"update_interval": "invalid_update_interval"}


async def test_update_interval_options(hass, mqtt_transport):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"topic": "test", "timeout": 60, "update_interval": 15}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({})["update_interval"] == 15
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"timeout": 60, "update_interval": 86400}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["update_interval"] == 86400


async def test_request_only_diagnostics_recovery_and_reconnect(hass, mqtt_transport):
    import struct
    from types import SimpleNamespace

    from custom_components.solis_sdm630_sniffer.protocol import crc16

    now = [0.0]
    entry = MockConfigEntry(
        domain=DOMAIN, data={"topic": "secret/topic", "timeout": 60}
    )
    runtime = entry.runtime_data = SnifferRuntime(
        hass, "secret/topic", 60, clock=lambda: now[0]
    )
    await runtime.async_start()
    try:
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "no_recent_requests_or_paired_responses"
        assert diagnostics["parser"]["last_request"] is None
        captured_request = bytes.fromhex("01040034000a31c3")
        for timestamp in (0, 0.07, 0.14):
            now[0] = timestamp
            runtime.async_message_received(
                SimpleNamespace(payload=captured_request, retain=False)
            )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "requests_without_paired_responses"
        assert diagnostics["parser"]["last_request"] == {
            "start": 52,
            "count": 10,
            "age": 0,
        }
        assert diagnostics["parser"]["counters"]["replaced_requests"] == 2
        assert not runtime.values
        assert not runtime.is_available(52)
        assert "secret/topic" not in json.dumps(diagnostics)
        assert captured_request.hex() not in json.dumps(diagnostics)

        now[0] = 1
        bodies = (
            bytes.fromhex("010400340002"),
            b"\x01\x04\x04" + struct.pack(">f", -1200),
        )
        paired_frames = b"".join(
            body + crc16(body).to_bytes(2, "little") for body in bodies
        )
        runtime.async_message_received(
            SimpleNamespace(payload=paired_frames, retain=False)
        )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "receiving_responses"
        assert diagnostics["parser"]["pending_request"] is None
        assert diagnostics["parser"]["last_request"]["start"] == 52
        now[0] = 61
        runtime.async_message_received(
            SimpleNamespace(payload=captured_request, retain=False)
        )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "requests_without_paired_responses"
        now[0] = 121
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "no_recent_requests_or_paired_responses"

        runtime.async_connection_changed(False)
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "disconnected"
        assert diagnostics["parser"]["last_request"] is None
        runtime.async_connection_changed(True)
        runtime.async_message_received(
            SimpleNamespace(payload=captured_request, retain=True)
        )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["traffic_status"] == "no_recent_requests_or_paired_responses"
    finally:
        runtime.async_stop()
