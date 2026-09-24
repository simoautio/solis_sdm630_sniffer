"""Real Home Assistant fixtures; only MQTT transport is mocked."""

from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow loading this integration from the repository."""
    yield


@pytest.fixture
def mqtt_transport():
    with (
        patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as subscribe,
        patch(
            "homeassistant.components.mqtt.async_subscribe_connection_status"
        ) as connection,
        patch("homeassistant.components.mqtt.is_connected", return_value=True),
        patch(
            "homeassistant.components.mqtt.mqtt_config_entry_enabled", return_value=True
        ),
        patch(
            "homeassistant.components.mqtt.async_publish",
            side_effect=AssertionError("Must never publish"),
        ),
    ):
        subscribe.return_value = Mock()
        connection.return_value = Mock()
        yield subscribe, connection
