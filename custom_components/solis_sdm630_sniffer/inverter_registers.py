"""Explicit S6-EH3P(5-10)K-H input-register profile (model 0x3306).

Sources: Solis Hybrid RTU protocol and Solis Smart Control V1.0, page 15.
Addresses are wire addresses, words/bytes are high first. Unknown values are
not evidence of additional supported hardware. Battery/PV3/PV4 are omitted.
"""

from dataclasses import dataclass

STATUS = {
    0: "Waiting", 1: "Open loop", 2: "Soft start", 3: "Generating",
    0x2010: "Failsafe", 0x2011: "Meter communication failure",
    0x2012: "Battery communication failure", 0x2019: "Meter selection failure",
}


@dataclass(frozen=True)
class InverterRegister:
    """A documented sensor, including its native resolution and identity."""

    key: str
    name: str
    address: int
    count: int = 1
    scale: float = 1
    signed: bool = False
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = "measurement"
    diagnostic: bool = False

    def decode(self, words: tuple[int, ...]) -> float | int | str:
        if len(words) != self.count:
            raise ValueError("Incorrect register count")
        value = 0
        for word in words:
            value = value << 16 | word
        if self.signed and value & (1 << (self.count * 16 - 1)):
            value -= 1 << (self.count * 16)
        if self.key == "status":
            return STATUS.get(value, f"Unknown (0x{value:04X})")
        return value * self.scale


R = InverterRegister
REGISTERS = (
    R("model", "Model code", 33000, state_class=None, diagnostic=True),
    R("dsp_version", "DSP version code", 33001, state_class=None, diagnostic=True),
    R("hmi_version", "HMI version code", 33002, state_class=None, diagnostic=True),
    R("protocol_version", "Protocol version", 33003, state_class=None, diagnostic=True),
    R("production_total", "PV production total", 33029, 2, unit="kWh", device_class="energy", state_class="total_increasing"),
    R("production_month", "PV production this month", 33031, 2, unit="kWh", device_class="energy", state_class="total_increasing"),
    R("production_last_month", "PV production last month", 33033, 2, unit="kWh", device_class="energy", state_class=None),
    R("production_today", "PV production today", 33035, scale=0.1, unit="kWh", device_class="energy", state_class="total_increasing"),
    R("production_yesterday", "PV production yesterday", 33036, scale=0.1, unit="kWh", device_class="energy", state_class=None),
    R("production_year", "PV production this year", 33037, 2, unit="kWh", device_class="energy", state_class="total_increasing"),
    R("production_last_year", "PV production last year", 33039, 2, unit="kWh", device_class="energy", state_class=None),
    *(R(f"pv{phase}_{kind}", f"PV {phase} {kind}", 33049 + (phase - 1) * 2 + offset, scale=0.1, unit=unit, device_class=kind)
      for phase in (1, 2) for kind, offset, unit in (("voltage", 0, "V"), ("current", 1, "A"))),
    R("pv_dc_power", "PV DC power", 33057, 2, unit="W", device_class="power"),
    *(R(f"ac_{kind}_{phase}", f"AC {kind} phase {phase}", base + phase - 1, scale=0.1, unit=unit, device_class=kind)
      for kind, base, unit in (("voltage", 33073, "V"), ("current", 33076, "A")) for phase in (1, 2, 3)),
    R("inverting_power", "Internal inverting power", 33079, 2, signed=True, unit="W", device_class="power"),
    R("reactive_power", "Reactive power", 33081, 2, signed=True, unit="var", device_class="reactive_power"),
    R("apparent_power", "Apparent power", 33083, 2, unit="VA", device_class="apparent_power"),
    R("temperature", "Inverter temperature", 33093, scale=0.1, signed=True, unit="°C", device_class="temperature"),
    R("frequency", "AC frequency", 33094, scale=0.01, unit="Hz", device_class="frequency"),
    R("status", "Operating status", 33095, state_class=None),
    *(R(key, name, address, state_class=None, diagnostic=True) for key, name, address in (
        ("grid_faults", "Grid fault bits", 33116), ("backup_faults", "Backup fault bits", 33117),
        ("inverter_faults_1", "Inverter fault bits 1", 33119), ("inverter_faults_2", "Inverter fault bits 2", 33120),
        ("operating_bits", "Operating status bits", 33121))),
    R("reported_household_power", "Inverter-reported household power", 33147, unit="W", device_class="power", diagnostic=True),
    R("backup_power", "Backup output power", 33148, unit="W", device_class="power"),
    R("ac_grid_power", "AC grid-port power", 33151, 2, signed=True, unit="W", device_class="power"),
    R("reported_import_total", "Inverter-reported import energy", 33169, 2, unit="kWh", device_class="energy", state_class="total_increasing", diagnostic=True),
    R("reported_export_total", "Inverter-reported export energy", 33173, 2, unit="kWh", device_class="energy", state_class="total_increasing", diagnostic=True),
    R("reported_household_total", "Inverter-reported household energy", 33580, 2, unit="kWh", device_class="energy", state_class="total_increasing", diagnostic=True),
    R("reported_grid_power", "Inverter-reported meter power", 33263, 2, signed=True, unit="W", device_class="power", diagnostic=True),
)

# Bounded documented blocks; illegal blocks are retried as individual sensors.
BLOCKS = ((33000, 4), (33029, 12), (33049, 10), (33073, 23),
          (33116, 6), (33147, 6), (33169, 6), (33263, 2), (33580, 2))
