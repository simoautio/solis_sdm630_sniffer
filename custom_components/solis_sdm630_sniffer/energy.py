"""Pure calculations for meter power; never infer solar yield from grid flow."""

import math


def combined_power(ac, backup, grid):
    """Return solar delivery and household watts for a battery-free system."""
    if any(value is None or not math.isfinite(value) for value in (ac, backup)):
        return None, None
    delivery = ac + backup
    solar = max(0.0, delivery)
    if grid is None or not math.isfinite(grid):
        return solar, None
    household = delivery + grid
    return solar, max(0.0, household) if household >= -50 else None


class EnergyEstimate:
    """Trapezoidal kWh estimate; callers explicitly break continuity on gaps."""

    def __init__(self, total: float = 0):
        self.total = total if math.isfinite(total) and total >= 0 else 0.0
        self.previous = None

    def update(self, now: float, power: float | None) -> float:
        if power is None or not math.isfinite(power) or power < 0:
            self.previous = None
            return self.total
        if self.previous is not None:
            stamp, value = self.previous
            if now > stamp:
                self.total += (value + power) / 2 * (now - stamp) / 3_600_000
        self.previous = now, power
        return self.total


class DailyCounterTotal:
    """Lifetime kWh built from the inverter's daily counter, immune to glitches.

    The daily counter has 0.1 kWh resolution but resets at the inverter's
    midnight, and a single bad read (a zero, typically) would look like a reset
    and replay the whole day into one hour of statistics. A reset is therefore
    believed only when the "yesterday" register takes over the finished day.
    Persisting the last readings bridges restarts and outages within a day.
    """

    MAX_DAILY = 500.0  # kWh; far beyond a 10 kW inverter, below garbage reads.
    REBASE_AFTER = 10  # Consecutive contradictory readings before giving in.

    def __init__(self, total=0, today=None, yesterday=None):
        self.total = total if self._valid(total, math.inf) else 0.0
        valid = self._valid(today) and self._valid(yesterday)
        self.today, self.yesterday = (today, yesterday) if valid else (None, None)
        self._rejected = 0

    @staticmethod
    def _valid(value, limit=MAX_DAILY):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= limit
        )

    def update(self, today, yesterday) -> float:
        if not (self._valid(today) and self._valid(yesterday)):
            return self.total
        if self.today is None:
            gained = 0.0  # First reading ever: only a baseline.
        elif yesterday == self.yesterday and today >= self.today:
            gained = today - self.today
        elif yesterday >= self.today and (
            yesterday != self.yesterday or yesterday == self.today > today
        ):
            # A new day. Production between the last reading and midnight is
            # not claimed: the register may be several days ahead by now.
            gained = today
        else:
            # A drop without a finished day behind it is a bad read. Only a
            # changed "yesterday" that keeps contradicting us (days were missed
            # and the last one produced less) is eventually trusted.
            self._rejected += yesterday != self.yesterday
            if self._rejected < self.REBASE_AFTER:
                return self.total
            gained = 0.0
        self._rejected = 0
        self.today, self.yesterday = today, yesterday
        self.total = round(self.total + gained, 1)
        return self.total

    def as_dict(self):
        return {"total": self.total, "today": self.today, "yesterday": self.yesterday}


def split_grid_power(
    power: float | None,
    import_sign: str,
) -> tuple[float | None, float | None]:
    """Return nonnegative (import, export) watts for the chosen sign convention."""
    if power is None or not math.isfinite(power):
        return None, None
    grid_power = -power if import_sign == "negative" else power
    return max(grid_power, 0.0), max(-grid_power, 0.0)
