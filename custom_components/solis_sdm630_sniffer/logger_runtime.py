"""Independent read-only inverter polling and fresh-source energy estimates."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CONF_GRID_IMPORT_SIGN,
    CONF_LOGGER_HOST,
    CONF_LOGGER_INTERVAL,
    CONF_LOGGER_PORT,
    CONF_LOGGER_UNIT,
    DEFAULT_GRID_IMPORT_SIGN,
    DEFAULT_LOGGER_INTERVAL,
    DEFAULT_LOGGER_PORT,
    DEFAULT_LOGGER_UNIT,
    DOMAIN,
)
from .energy import EnergyEstimate, combined_power
from .inverter_registers import BLOCKS, REGISTERS
from .modbus_tcp import ModbusError, ModbusReader, UnsupportedRegisters

_LOGGER = logging.getLogger(__name__)


class LoggerRuntime:
    """Own logger samples without coupling meter availability to logger failures."""

    def __init__(self, hass, meter, entry_id, options):
        self.hass, self.meter = hass, meter
        self.host = options[CONF_LOGGER_HOST]
        self.port = int(options.get(CONF_LOGGER_PORT, DEFAULT_LOGGER_PORT))
        self.unit = int(options.get(CONF_LOGGER_UNIT, DEFAULT_LOGGER_UNIT))
        self.interval = float(
            options.get(CONF_LOGGER_INTERVAL, DEFAULT_LOGGER_INTERVAL)
        )
        self.import_sign = options.get(CONF_GRID_IMPORT_SIGN, DEFAULT_GRID_IMPORT_SIGN)
        self.clock = monotonic
        self.values = {}
        self.updated_at = {}
        self.listeners: set[Callable[[], None]] = set()
        self.solar, self.household = EnergyEstimate(), EnergyEstimate()
        self.store = Store(hass, 1, f"{DOMAIN}.{entry_id}.energy")
        self.failures = 0
        self.last_error = None
        self.balance_status = "waiting_for_sources"
        self.unsupported: set[str] = set()
        self._split_blocks = set()
        self._cancel_timer = None
        self._cancel_expiry = None
        self._remove_meter_listener = None
        self._task = None
        self._running = False
        self._loaded = False

    async def async_start(self):
        data = await self.store.async_load() or {}
        for key, counter in (("solar", self.solar), ("household", self.household)):
            value = data.get(key, 0)
            if isinstance(value, (int, float)):
                counter.total = EnergyEstimate(value).total
        self._loaded = True
        self._running = True
        self._remove_meter_listener = self.meter.async_add_listener(self._meter_changed)
        self._schedule(0)

    async def async_stop(self):
        self._running = False
        for cancel in (
            self._cancel_timer,
            self._cancel_expiry,
            self._remove_meter_listener,
        ):
            if cancel:
                cancel()
        self._cancel_timer = self._cancel_expiry = self._remove_meter_listener = None
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._loaded:  # Never overwrite totals that failed to load.
            await self.store.async_save(self._stored_data())
        self.listeners.clear()

    def _stored_data(self):
        return {"solar": self.solar.total, "household": self.household.total}

    def async_add_listener(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def _notify(self):
        for listener in tuple(self.listeners):
            listener()

    def is_available(self, key):
        return (
            self._running
            and key in self.values
            and self.clock() - self.updated_at.get(key, float("-inf"))
            < self.interval * 2 + 5
        )

    def _schedule(self, delay):
        if self._cancel_timer:
            self._cancel_timer()
        if self._running:
            self._cancel_timer = async_call_later(self.hass, delay, self._begin_poll)

    @callback
    def _begin_poll(self, _now):
        self._cancel_timer = None
        if self._running:
            self._task = self.hass.async_create_background_task(
                self.async_poll(), "Solis logger poll"
            )

    async def _read_block(self, client, start, count, values, stamps):
        descriptions = [
            r
            for r in REGISTERS
            if start <= r.address and r.address + r.count <= start + count
        ]
        if start not in self._split_blocks:
            try:
                words = await client.read(start, count)
            except UnsupportedRegisters:
                self._split_blocks.add(start)
            else:
                now = self.clock()
                for item in descriptions:
                    offset = item.address - start
                    values[item.key] = item.decode(words[offset : offset + item.count])
                    stamps[item.key] = now
                return
        for item in descriptions:
            if item.key in self.unsupported:
                continue
            try:
                words = await client.read(item.address, item.count)
            except UnsupportedRegisters:
                self.unsupported.add(item.key)
            else:
                values[item.key] = item.decode(words)
                stamps[item.key] = self.clock()

    async def async_poll(self):
        """Publish only coherent completed cycles; failures never become zeros."""
        started = self.clock()
        try:
            values, stamps = {}, {}
            async with ModbusReader(self.host, self.port, self.unit) as client:
                for start, count in BLOCKS:
                    await self._read_block(client, start, count, values, stamps)
                    if start == 33000 and values.get("model") != 0x3306:
                        raise ModbusError("Unsupported inverter model")
            if not self._running:
                return
            now = self.clock()
            if (
                self.updated_at
                and now - max(self.updated_at.values()) > self.interval * 2 + 5
            ):
                self.solar.update(now, None)
                self.household.update(now, None)
            self.values, self.updated_at = values, stamps
            for phase in (1, 2):
                voltage, current = (f"pv{phase}_voltage", f"pv{phase}_current")
                if voltage in values and current in values:
                    key = f"pv{phase}_power"
                    values[key] = values[voltage] * values[current]
                    stamps[key] = min(stamps[voltage], stamps[current])
            self.update_combined(now)
            self.failures = 0
            self.last_error = None
            self.store.async_delay_save(self._stored_data, 60)
        except (OSError, TimeoutError, ModbusError) as err:
            self.failures += 1
            # Error type only: network exceptions can contain private hostnames.
            self.last_error = type(err).__name__
            self.values.clear()
            self.updated_at.clear()
            self.solar.update(self.clock(), None)
            self.household.update(self.clock(), None)
            self.balance_status = "logger_unavailable"
            _LOGGER.debug("Logger polling failed: %s", self.last_error)
        finally:
            if self._running:
                self._notify()
                if self._cancel_expiry:
                    self._cancel_expiry()
                if self.updated_at:
                    delay = max(
                        0,
                        min(self.updated_at.values())
                        + 2 * self.interval
                        + 5
                        - self.clock(),
                    )
                    self._cancel_expiry = async_call_later(
                        self.hass, delay, self._expire
                    )
                delay = (
                    min(300, self.interval * 2 ** min(self.failures, 5))
                    if self.failures
                    else max(0, self.interval - (self.clock() - started))
                )
                self._schedule(delay)

    @callback
    def _expire(self, _now):
        self._cancel_expiry = None
        now = self.clock()
        expired = [key for key in self.values if not self.is_available(key)]
        for key in expired:
            self.values.pop(key, None)
            self.updated_at.pop(key, None)
        if expired:
            self.solar.update(now, None)
            self.household.update(now, None)
            self.values.pop("solar_ac_power", None)
            self.values.pop("estimated_solar_energy", None)
            self._invalidate_household()
            self._notify()

    def _invalidate_household(self):
        for key in ("household_power", "estimated_household_energy"):
            self.values.pop(key, None)
            self.updated_at.pop(key, None)
        self.household.update(self.clock(), None)

    @callback
    def _meter_changed(self):
        if not self.meter.is_available(52):
            self._invalidate_household()
            self.balance_status = "meter_unavailable"
            self._notify()

    def update_combined(self, now):
        ac_stamp = self.updated_at.get("ac_grid_power", now)
        grid = None
        self.balance_status = "meter_unavailable"
        if self.meter.is_available(52):
            self.balance_status = "unaligned_samples"
            if abs(ac_stamp - self.meter.updated_at[52]) <= 5:
                grid = self.meter.latest_value(52)
                if grid is not None and self.import_sign == "negative":
                    grid = -grid
                self.balance_status = "ok"
        solar, household = combined_power(
            self.values.get("ac_grid_power"), self.values.get("backup_power"), grid
        )
        if solar is None:
            self.balance_status = "inverter_output_unavailable"
        elif grid is not None and household is None:
            self.balance_status = "negative_household_balance"
        for name, power, counter in (
            ("solar", solar, self.solar),
            ("household", household, self.household),
        ):
            power_key = "solar_ac_power" if name == "solar" else "household_power"
            energy_key = f"estimated_{name}_energy"
            counter.update(ac_stamp, power)
            for key in (power_key, energy_key):
                self.values.pop(key, None)
                self.updated_at.pop(key, None)
            if power is not None:
                self.values[power_key] = power
                self.values[energy_key] = counter.total
                self.updated_at[power_key] = self.updated_at[energy_key] = ac_stamp
