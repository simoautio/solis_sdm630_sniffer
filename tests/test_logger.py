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
def test_read_only_tcp_frames(failure):
    mod = load("modbus_tcp")

    async def run():
        async def serve(reader, writer):
            try:
                request = await reader.readexactly(12)
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
                if failure == "timeout":
                    await reader.read()
                    return
                writer.write(header[:3])
                await writer.drain()
                await asyncio.sleep(0)
                writer.write(header[3:] + (body[:1] if failure == "short" else body))
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        async with server:
            client = mod.ModbusReader(
                "127.0.0.1", server.sockets[0].getsockname()[1], 1, timeout=0.1
            )
            async with client:
                if failure:
                    with pytest.raises((mod.ModbusError, TimeoutError)):
                        await client.read(33151, 2)
                else:
                    assert await client.read(33151, 2) == (65535, 65526)

    asyncio.run(run())


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
