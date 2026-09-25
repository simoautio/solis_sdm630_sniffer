"""Configuration and diagnostic contract tests."""

import json
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solis_sdm630_sniffer.config_flow import (
    SnifferConfigFlow,
    _logger_options,
)
from custom_components.solis_sdm630_sniffer.const import DOMAIN
from custom_components.solis_sdm630_sniffer.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.solis_sdm630_sniffer.runtime import SnifferRuntime


async def open_options(hass, entry, step):
    """Open Configure and choose one menu page."""
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] == FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": step}
    )


async def test_defaults_and_create(hass, mqtt_transport):
    flow = SnifferConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow.handler = DOMAIN
    form = await flow.async_step_meter()
    assert form["type"] == FlowResultType.FORM
    assert form["data_schema"]({}) == {
        "topic": "solis/rs485/raw",
        "timeout": 60,
        "update_interval": 30,
    }
    result = await flow.async_step_meter({"topic": "solis/rs485/raw", "timeout": 60})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["topic"] == "solis/rs485/raw"


SKIP_SETUP = "custom_components.solis_sdm630_sniffer.async_setup_entry"


async def start_setup(hass, mode):
    """Open Add integration and choose what to monitor."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mode": mode}
    )


async def test_logger_only_setup_needs_no_mqtt(hass):
    with (
        patch(
            "homeassistant.components.mqtt.mqtt_config_entry_enabled",
            return_value=False,
        ),
        patch(SKIP_SETUP, return_value=True),
    ):
        form = await start_setup(hass, "logger")
        assert form["step_id"] == "logger"
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": ""}
        )
        assert result["errors"] == {"logger_host": "logger_required"}
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": "http://x/"}
        )
        assert result["errors"] == {"logger_host": "invalid_logger"}
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": "192.168.1.135"}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Solis inverter"
        assert result["data"] == {}
        assert result["options"]["logger_host"] == "192.168.1.135"
        assert result["options"]["logger_port"] == 502
        # The same logger cannot be added twice.
        form = await start_setup(hass, "logger")
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": "192.168.1.135"}
        )
        assert result["reason"] == "already_configured"


async def test_both_setup_stores_meter_data_and_logger_options(hass, mqtt_transport):
    with patch(SKIP_SETUP, return_value=True):
        form = await start_setup(hass, "both")
        assert form["step_id"] == "meter"
        form = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"topic": "t", "timeout": 60}
        )
        assert form["step_id"] == "logger"
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": "192.168.1.135"}
        )
    assert result["title"] == "Solis SDM630 Sniffer"
    assert result["data"]["topic"] == "t"
    assert "logger_host" not in result["data"]
    assert result["options"]["logger_host"] == "192.168.1.135"
    assert result["result"].unique_id == "t"


@pytest.mark.parametrize("mode", ["meter", "both"])
async def test_meter_modes_require_mqtt(hass, mode):
    with patch(
        "homeassistant.components.mqtt.mqtt_config_entry_enabled", return_value=False
    ):
        result = await start_setup(hass, mode)
    assert result["reason"] == "mqtt_required"


async def test_logger_only_options(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={"logger_host": "192.168.1.135"}
    )
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["menu_options"] == ["logger", "utility_meters"]
    form = await open_options(hass, entry, "logger")
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"logger_host": ""}
    )
    assert result["errors"] == {"logger_host": "logger_required"}
    form = await open_options(hass, entry, "utility_meters")
    assert form["data_schema"]({})["utility_meter_sources"] == ["solar"]


@pytest.mark.parametrize("topic", ["", "a/#", "a/+", "a\0b"])
async def test_invalid_topic(hass, mqtt_transport, topic):
    flow = SnifferConfigFlow()
    flow.hass = hass
    result = await flow.async_step_meter({"topic": topic, "timeout": 60})
    assert result["errors"] == {"topic": "invalid_topic"}


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
async def test_invalid_timeout(hass, mqtt_transport, timeout):
    flow = SnifferConfigFlow()
    flow.hass = hass
    result = await flow.async_step_meter({"topic": "test", "timeout": timeout})
    assert result["errors"] == {"timeout": "invalid_timeout"}


async def test_mqtt_required(hass):
    flow = SnifferConfigFlow()
    flow.hass = hass
    with patch(
        "homeassistant.components.mqtt.mqtt_config_entry_enabled", return_value=False
    ):
        assert (await flow.async_step_meter())["reason"] == "mqtt_required"


@pytest.mark.parametrize(
    "field,value",
    [
        ("logger_port", 0),
        ("logger_port", True),
        ("logger_unit", 248),
        ("logger_interval", 9),
        ("logger_interval", float("nan")),
        ("logger_host", "http://logger/"),
        ("logger_host", "192.168.1.135:502"),
    ],
)
def test_invalid_logger_options(field, value):
    errors = {}
    _logger_options({"logger_host": "192.168.1.135", field: value}, {}, errors)
    assert errors == {field: "invalid_logger"}


async def test_invalid_logger_host_is_retryable(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"topic": "test", "timeout": 60})
    entry.add_to_hass(hass)
    form = await open_options(hass, entry, "logger")
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"logger_host": "http://x/"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"logger_host": "invalid_logger"}
    assert entry.options == {}


def test_empty_logger_host_disables_polling():
    errors = {}
    assert _logger_options({"logger_host": "  ", "logger_port": 0}, {}, errors) == {}
    assert errors == {}


async def test_logger_options_preserve_meter_settings(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"topic": "test", "timeout": 60},
        options={"grid_import_sign": "negative"},
    )
    entry.add_to_hass(hass)
    form = await open_options(hass, entry, "logger")
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"logger_host": "192.168.1.135"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["logger_port"] == 502
    assert entry.options["logger_unit"] == 1
    assert entry.options["logger_interval"] == 30
    assert entry.options["grid_import_sign"] == "negative"
    form = await open_options(hass, entry, "meter")
    await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"timeout": 90}
    )
    assert entry.options["logger_host"] == "192.168.1.135"
    form = await open_options(hass, entry, "logger")
    await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={"logger_host": ""}
    )
    assert not any(key.startswith("logger_") for key in entry.options)


async def test_duplicate_topic(hass, mqtt_transport):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="test", data={"topic": "test", "timeout": 60}
    )
    entry.add_to_hass(hass)
    # Use the real manager to translate the duplicate AbortFlow into a result.
    form = await start_setup(hass, "meter")
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"topic": "test", "timeout": 60}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options(hass, mqtt_transport):
    entry = MockConfigEntry(domain=DOMAIN, data={"topic": "test", "timeout": 60})
    entry.add_to_hass(hass)
    result = await open_options(hass, entry, "meter")
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"timeout": 120}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "timeout": 120,
        "grid_import_sign": "positive",
        "update_interval": 30,
        "meter_reversed": False,
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
    result = await flow.async_step_meter(
        {"topic": "test", "timeout": 60, "update_interval": interval}
    )
    assert result["errors"] == {"update_interval": "invalid_update_interval"}


async def test_update_interval_options(hass, mqtt_transport):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"topic": "test", "timeout": 60, "update_interval": 15}
    )
    entry.add_to_hass(hass)
    result = await open_options(hass, entry, "meter")
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


@pytest.mark.parametrize("existing_mode", ["logger", "both"])
@pytest.mark.parametrize("new_mode", ["logger", "both"])
async def test_duplicate_logger_across_modes(
    hass, mqtt_transport, existing_mode, new_mode
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="logger_logger.test" if existing_mode == "logger" else "old/topic",
        data={} if existing_mode == "logger" else {"topic": "old/topic"},
        options={"logger_host": "LOGGER.TEST"},
    )
    entry.add_to_hass(hass)
    with patch(SKIP_SETUP, return_value=True):
        form = await start_setup(hass, new_mode)
        if new_mode == "both":
            form = await hass.config_entries.flow.async_configure(
                form["flow_id"], {"topic": "new/topic", "timeout": 60}
            )
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"logger_host": "logger.test", "logger_port": 502, "logger_unit": 1},
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize("data", [{}, {"topic": "new/topic"}])
async def test_duplicate_logger_options_retry_and_self(hass, data):
    other = MockConfigEntry(
        domain=DOMAIN,
        data={"topic": "old/topic"},
        options={"logger_host": "LOGGER.TEST"},
    )
    other.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, options={"logger_host": "own.test"}
    )
    entry.add_to_hass(hass)
    form = await open_options(hass, entry, "logger")
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"logger_host": "logger.test"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"logger_host": "logger_already_configured"}
    assert entry.options["logger_host"] == "own.test"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"logger_host": "own.test", "logger_interval": 60}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["logger_interval"] == 60


@pytest.mark.parametrize("endpoint", [{"logger_port": 503}, {"logger_unit": 2}])
async def test_distinct_logger_endpoints_allowed(hass, endpoint):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="logger_logger.test",
        data={},
        options={"logger_host": "logger.test"},
    )
    entry.add_to_hass(hass)
    with patch(SKIP_SETUP, return_value=True):
        form = await start_setup(hass, "logger")
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"logger_host": "logger.test", **endpoint}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
