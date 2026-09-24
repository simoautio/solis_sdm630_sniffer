"""Verify the public meter map and metadata without Home Assistant."""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sniffer_registers",
    Path(__file__).parents[1] / "custom_components/solis_sdm630_sniffer/registers.py",
)
registers = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = registers
spec.loader.exec_module(registers)


def test_meter_map():
    table = registers.REGISTERS
    assert set(table) == {
        0,
        2,
        4,
        6,
        8,
        10,
        12,
        14,
        16,
        18,
        20,
        22,
        24,
        26,
        28,
        30,
        32,
        34,
        42,
        46,
        48,
        52,
        56,
        60,
        62,
        70,
        72,
        74,
        200,
        202,
        204,
        206,
        342,
        346,
        348,
        350,
        352,
        354,
        356,
    }
    assert len({item.key for item in table.values()}) == len(table)
    assert table[0].unit == "V"
    assert table[52].device_class == "power"
    assert table[60].unit == "var"
    assert table[62].unit is None
    assert table[72].state_class == "total_increasing"
    assert table[74].unit == "kWh"
    assert table[342].key == "total_energy"
    assert all(address % 2 == 0 for address in table)
