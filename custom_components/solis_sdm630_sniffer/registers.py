"""SDM630MCT V1.7 register map (zero-based addresses, two registers per float)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Register:
    """Meter and Home Assistant metadata, kept independent of HA imports."""

    key: str
    name: str
    unit: str | None
    device_class: str
    state_class: str = "measurement"


REGISTERS: dict[int, Register] = {}
for base, key, name, unit, device_class in (
    (0, "voltage", "Voltage", "V", "voltage"),
    (6, "current", "Current", "A", "current"),
    (12, "active_power", "Active power", "W", "power"),
    (18, "apparent_power", "Apparent power", "VA", "apparent_power"),
    (24, "reactive_power", "Reactive power", "var", "reactive_power"),
    (30, "power_factor", "Power factor", None, "power_factor"),
):
    for phase in range(1, 4):
        REGISTERS[base + (phase - 1) * 2] = Register(
            f"l{phase}_{key}", f"L{phase} {name.lower()}", unit, device_class
        )

for address, key, name, unit, device_class in (
    (42, "average_voltage", "Average voltage", "V", "voltage"),
    (46, "average_current", "Average current", "A", "current"),
    (48, "sum_current", "Sum current", "A", "current"),
    (52, "total_active_power", "Total active power", "W", "power"),
    (56, "total_apparent_power", "Total apparent power", "VA", "apparent_power"),
    (60, "total_reactive_power", "Total reactive power", "var", "reactive_power"),
    (62, "total_power_factor", "Total power factor", None, "power_factor"),
    (70, "frequency", "Frequency", "Hz", "frequency"),
    (200, "l1_l2_voltage", "L1-L2 voltage", "V", "voltage"),
    (202, "l2_l3_voltage", "L2-L3 voltage", "V", "voltage"),
    (204, "l3_l1_voltage", "L3-L1 voltage", "V", "voltage"),
    (206, "average_line_voltage", "Average line voltage", "V", "voltage"),
):
    REGISTERS[address] = Register(key, name, unit, device_class)

for address, key, name in (
    (72, "import_energy", "Import energy"),
    (74, "export_energy", "Export energy"),
    (342, "total_energy", "Total energy"),
    (346, "l1_import_energy", "L1 import energy"),
    (348, "l2_import_energy", "L2 import energy"),
    (350, "l3_import_energy", "L3 import energy"),
    (352, "l1_export_energy", "L1 export energy"),
    (354, "l2_export_energy", "L2 export energy"),
    (356, "l3_export_energy", "L3 export energy"),
):
    REGISTERS[address] = Register(key, name, "kWh", "energy", "total_increasing")

# Import/export counter pairs. A meter mounted in reverse counts import as export.
_PAIRS = ((72, 74), (346, 352), (348, 354), (350, 356))
COUNTERPART = {a: b for pair in _PAIRS for a, b in (pair, pair[::-1])}
