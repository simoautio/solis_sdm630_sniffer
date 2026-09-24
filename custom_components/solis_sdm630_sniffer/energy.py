"""Pure calculations for meter power; never infer solar yield from grid flow."""

import math


def split_grid_power(
    power: float | None,
    import_sign: str,
) -> tuple[float | None, float | None]:
    """Return nonnegative (import, export) watts for the chosen sign convention."""
    if power is None or not math.isfinite(power):
        return None, None
    grid_power = -power if import_sign == "negative" else power
    return max(grid_power, 0.0), max(-grid_power, 0.0)
