"""Grid power direction is independent of the meter's lifetime counters."""

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sniffer_energy",
    Path(__file__).parents[1] / "custom_components/solis_sdm630_sniffer/energy.py",
)
energy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = energy
spec.loader.exec_module(energy)


@pytest.mark.parametrize(
    ("power", "sign", "expected"),
    [
        (1200, "positive", (1200, 0)),
        (-800, "positive", (0, 800)),
        (1200, "negative", (0, 1200)),
        (-800, "negative", (800, 0)),
        (0, "positive", (0, 0)),
        (0, "negative", (0, 0)),
        (0.25, "positive", (0.25, 0)),
    ],
)
def test_grid_direction(power, sign, expected):
    assert energy.split_grid_power(power, sign) == expected


def test_missing_sample_does_not_become_zero():
    assert energy.split_grid_power(None, "positive") == (None, None)


@pytest.mark.parametrize("power", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_sample_is_not_energy_data(power):
    assert energy.split_grid_power(power, "positive") == (None, None)
