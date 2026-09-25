"""Exercise real TCP framing without Home Assistant or live hardware."""

import asyncio
import importlib.util
import struct
import sys
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).parents[1]
        / "custom_components/solis_sdm630_sniffer"
        / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "transaction",
        "unit",
        "length",
        "function",
        "exception",
        "short",
        "timeout",
    ],
)
def test_read_only_tcp_frames(failure, monkeypatch):
    # In-memory stream: HA's test plugin blocks sockets.
    mod = load("modbus_tcp")

    class Writer:
        def __init__(self, reader):
            self.reader = reader

        def write(self, request):
            tid, proto, length, unit, function, address, count = struct.unpack(
                ">HHHBBHH", request
            )
            assert (proto, length, unit, function, address, count) == (
                0,
                6,
                1,
                4,
                33151,
                2,
            )
            if failure == "timeout":
                return
            body = bytes([4, 4]) + struct.pack(">HH", 65535, 65526)
            if failure == "function":
                body = bytes([3]) + body[1:]
            if failure == "exception":
                body = bytes([0x84, 2])
            header = struct.pack(
                ">HHHB",
                tid + (failure == "transaction"),
                0,
                999 if failure == "length" else len(body) + 1,
                2 if failure == "unit" else 1,
            )
            self.reader.feed_data(header + (body[:1] if failure == "short" else body))
            if failure == "short":
                self.reader.feed_eof()

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def open_connection(host, port):
        assert (host, port) == ("logger.test", 502)
        reader = asyncio.StreamReader()
        return reader, Writer(reader)

    monkeypatch.setattr(mod.asyncio, "open_connection", open_connection)

    async def run():
        async with mod.ModbusReader("logger.test", 502, 1, timeout=0.1) as client:
            if failure:
                with pytest.raises((mod.ModbusError, TimeoutError)):
                    await client.read(33151, 2)
            else:
                assert await client.read(33151, 2) == (65535, 65526)

    # A private loop: asyncio.run() would clear the loop HA's plugin relies on.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


def test_profile_scaling_and_signedness():
    mod = load("inverter_registers")
    by_key = {item.key: item for item in mod.REGISTERS}
    assert by_key["ac_grid_power"].decode((65535, 65526)) == -10
    assert by_key["pv1_voltage"].decode((3220,)) == 322
    assert by_key["production_today"].decode((19,)) == pytest.approx(1.9)
    assert by_key["production_total"].decode((1, 2)) == 65538
    assert by_key["status"].decode((0x2011,)) == "Meter communication failure"
    assert by_key["status"].decode((0xABCD,)) == "Unknown (0xABCD)"
    assert not any(
        item.key.startswith(("pv3", "pv4", "battery")) for item in mod.REGISTERS
    )


def test_energy_estimate_persistence_and_gaps():
    mod = load("energy")
    counter = mod.EnergyEstimate(12)
    assert counter.update(0, 1000) == 12
    assert counter.update(3600, 1000) == 13
    counter.update(3700, None)
    assert counter.update(7200, 1000) == 13
    assert counter.update(10800, 3000) == 15
    restored = mod.EnergyEstimate(counter.total)
    assert restored.update(20000, 3000) == 15


@pytest.mark.parametrize(
    "ac,backup,grid,expected",
    [
        (1000, 0, 500, (1000, 1500)),
        (1000, 200, -500, (1200, 700)),
        (-30, 0, 500, (0, 470)),
        (100, 0, -120, (100, 0)),
        (100, 0, -200, (100, None)),
        (None, 0, 500, (None, None)),
    ],
)
def test_household_balance(ac, backup, grid, expected):
    assert load("energy").combined_power(ac, backup, grid) == expected
