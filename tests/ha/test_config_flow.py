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
    assert form["data_schema"]({}) == {"topic": "solis/rs485/raw", "timeout": 60}
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
    assert entry.options == {"timeout": 120, "grid_import_sign": "positive"}


async def test_diagnostics_redacted(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"topic": "secret/topic", "timeout": 60}
    )
    entry.runtime_data = SnifferRuntime(hass, "secret/topic", 60)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "secret/topic" not in json.dumps(diagnostics)
    assert diagnostics["parser"]["buffer_size"] == 0
