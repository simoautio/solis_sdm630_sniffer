"""Push-only MQTT subscription and per-register freshness."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from time import monotonic

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .protocol import StreamParser
from .registers import REGISTERS

_LOGGER = logging.getLogger(__name__)


class SnifferRuntime:
    """Own one ordered stream, subscriptions, sensor values and expiry timer."""

    def __init__(
        self,
        hass: HomeAssistant,
        topic: str,
        timeout: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.hass = hass
        self.topic = topic
        self.timeout = timeout
        self.clock = clock
        self.parser = StreamParser()
        self.values: dict[int, float] = {}
        self.updated_at: dict[int, float] = {}
        self.last_response_at: float | None = None
        self.listeners: set[Callable[[], None]] = set()
        self._cleanup: list[Callable[[], None]] = []
        self._cancel_timer: Callable[[], None] | None = None
        self._connected = False
        self._running = False
        self._available: set[int] = set()

    async def async_start(self) -> None:
        """Subscribe using the shared MQTT connection without publishing."""
        self._running = True
        try:
            self._cleanup.append(
                mqtt.async_subscribe_connection_status(
                    self.hass, self.async_connection_changed
                )
            )
            self._connected = mqtt.is_connected(self.hass)
            self._cleanup.append(
                await mqtt.async_subscribe(
                    self.hass,
                    self.topic,
                    self.async_message_received,
                    qos=0,
                    encoding=None,
                )
            )
        except BaseException:
            self.async_stop()
            raise

    @callback
    def async_stop(self) -> None:
        """Idempotently release subscription, connection listener and timer."""
        self._running = False
        self._connected = False
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        while self._cleanup:
            self._cleanup.pop()()
        self.parser.reset()
        self.updated_at.clear()
        self.last_response_at = None
        self._available.clear()
        self.listeners.clear()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a sensor callback."""
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    @callback
    def async_connection_changed(self, connected: bool) -> None:
        """Never carry frame fragments or availability across MQTT reconnects."""
        self._connected = connected
        self.parser.reset()
        self.updated_at.clear()
        self.last_response_at = None
        self.async_check_expiry()

    @callback
    def async_message_received(self, message: mqtt.ReceiveMessage) -> None:
        """Decode binary traffic; historical retained samples are ignored."""
        if not self._running or not self._connected or message.retain:
            return
        if not isinstance(message.payload, (bytes, bytearray)):
            _LOGGER.debug("Ignored nonbinary MQTT payload")
            return
        now = self.clock()
        updates = self.parser.feed(bytes(message.payload), now)
        changed = False
        for update in updates:
            self.last_response_at = now
            for address, value in update.values.items():
                description = REGISTERS.get(address)
                if description is None:
                    continue
                if description.state_class == "total_increasing" and value < 0:
                    _LOGGER.debug(
                        "Ignored negative cumulative energy at register %d", address
                    )
                    continue
                changed |= self.values.get(address) != value
                self.values[address] = value
                self.updated_at[address] = now
        self._refresh(now, changed)

    def is_available(self, address: int) -> bool:
        """Both the stream and this specific reading must be fresh."""
        now = self.clock()
        return (
            self._running
            and self._connected
            and self.last_response_at is not None
            and now - self.last_response_at < self.timeout
            and address in self.updated_at
            and now - self.updated_at[address] < self.timeout
        )

    @callback
    def async_check_expiry(self, _now: datetime | None = None) -> None:
        """Publish availability transitions even while MQTT is silent."""
        self._refresh(self.clock(), False)

    def _refresh(self, now: float, changed: bool) -> None:
        available = {
            address for address in self.updated_at if self.is_available(address)
        }
        if available != self._available:
            changed = True
            if bool(available) != bool(self._available):
                _LOGGER.debug(
                    "Meter sensors %s", "available" if available else "unavailable"
                )
            self._available = available
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        if available:
            deadline = min(
                self.updated_at[address] + self.timeout for address in available
            )
            self._cancel_timer = async_call_later(
                self.hass, max(0, deadline - now), self.async_check_expiry
            )
        if changed:
            for listener in tuple(self.listeners):
                listener()
