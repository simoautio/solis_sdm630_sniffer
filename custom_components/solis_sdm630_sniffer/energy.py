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


def split_grid_power(
    power: float | None,
    import_sign: str,
) -> tuple[float | None, float | None]:
    """Return nonnegative (import, export) watts for the chosen sign convention."""
    if power is None or not math.isfinite(power):
        return None, None
    grid_power = -power if import_sign == "negative" else power
    return max(grid_power, 0.0), max(-grid_power, 0.0)
