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


def feed(counter, *readings):
    for today, yesterday in readings:
        counter.update(today, yesterday)
    return counter.total


def test_daily_counter_accumulates_across_midnight():
    counter = energy.DailyCounterTotal()
    # The first reading is a baseline: energy from before is not claimed.
    assert feed(counter, (4.0, 9.0)) == 0
    assert feed(counter, (4.3, 9.0), (12.5, 9.0)) == 8.5
    # Midnight: "yesterday" takes over the finished day, "today" restarts.
    assert feed(counter, (0.0, 12.5), (0.0, 12.5), (0.7, 12.5)) == 9.2


@pytest.mark.parametrize(
    "glitch",
    [
        (0.0, 9.0),  # Only the daily counter read as zero.
        (0.0, 0.0),  # The whole block read as zeros.
        (3.0, 9.0),  # A lower value without a finished day behind it.
        (6553.5, 9.0),  # Garbage far beyond a day's production.
        (float("nan"), 9.0),
        (None, 9.0),
        (5.0, None),
    ],
)
def test_bad_read_never_replays_the_day(glitch):
    counter = energy.DailyCounterTotal(100, 5.0, 9.0)
    assert feed(counter, glitch, glitch, (5.2, 9.0)) == 100.2


def test_zero_block_before_sunrise_adds_nothing():
    counter = energy.DailyCounterTotal(100, 0.0, 9.0)
    assert feed(counter, (0.0, 0.0), (0.0, 9.0), (0.4, 9.0)) == 100.4


def test_identical_consecutive_days_still_roll_over():
    counter = energy.DailyCounterTotal(100, 12.3, 12.3)
    assert feed(counter, (0.0, 12.3), (0.5, 12.3)) == 100.5


def test_restart_bridges_the_same_day_and_a_missed_midnight():
    saved = energy.DailyCounterTotal(100, 5.0, 9.0).as_dict()
    assert feed(energy.DailyCounterTotal(**saved), (7.5, 9.0)) == 102.5
    # Offline past midnight: the new day is counted, the old day's tail is not.
    assert feed(energy.DailyCounterTotal(**saved), (2.0, 11.0)) == 102


def test_missed_days_with_a_poorer_day_recover_without_a_jump():
    counter = energy.DailyCounterTotal(100, 30.0, 9.0)
    # Days were missed and the last one produced less than our last reading.
    assert feed(counter, *[(1.0, 2.0)] * 9) == 100
    assert feed(counter, (1.0, 2.0), (1.5, 2.0)) == 100.5


def test_corrupt_stored_state_starts_clean():
    counter = energy.DailyCounterTotal("x", -1, None)
    assert (counter.total, counter.today, counter.yesterday) == (0, None, None)
    assert feed(counter, (5.0, 9.0), (5.5, 9.0)) == 0.5
