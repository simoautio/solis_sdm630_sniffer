# Solis SDM630 Sniffer

[![Tests](https://github.com/simoautio/solis_sdm630_sniffer/actions/workflows/tests.yml/badge.svg)](https://github.com/simoautio/solis_sdm630_sniffer/actions/workflows/tests.yml)

A Home Assistant custom integration that **passively reads Eastron SDM630MCT meter traffic** captured by a PUSR USR-DR134 serial-to-MQTT gateway. Intended for an existing Solis-to-meter RS485 link.

The integration subscribes to raw binary MQTT messages and creates native sensors. It **never publishes MQTT messages, sends Modbus requests, or changes the meter**. Home Assistant's shared MQTT integration can independently publish its own birth/status messages.

## Requirements

- Home Assistant **2026.1 or later** with its built-in **MQTT integration configured and enabled**.
- An SDM630MCT at Modbus slave address **1**, with an existing master polling function **0x04** input registers.
- A gateway capture that publishes **both requests and responses**, in serial order, on one exact MQTT topic. Default: `solis/rs485/raw`.
- Raw binary payloads, not hexadecimal text, Base64, JSON, or Modbus TCP.

Only readings requested by the existing master can populate. Installing this integration does not make the Solis inverter poll additional registers.

## Install with HACS

On your **Home Assistant machine**:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/simoautio/solis_sdm630_sniffer` with type **Integration**.
3. Find **Solis SDM630 Sniffer** and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → Solis SDM630 Sniffer**.
6. Enter the MQTT topic and availability timeout (default **60 seconds**).

This is a HACS **custom repository**, not a listing in HACS's default catalog. No Home Assistant installation is needed on the computer used to clone or develop this repository.

## Manual installation

Download a release or clone this repository. Copy the directory
`custom_components/solis_sdm630_sniffer` into your Home Assistant configuration directory:

```text
/config/custom_components/solis_sdm630_sniffer/
    __init__.py
    manifest.json
    ...
```

Restart Home Assistant, then add the integration through Settings as above. Do not add YAML sensor definitions or broker credentials for this integration; it uses the existing MQTT connection.

## Gateway setup

Configure the USR-DR134 to forward the observed serial stream transparently to the chosen MQTT topic:

- Match the serial baud rate, parity, data bits, and stop bits of the existing meter bus.
- Capture both the master's requests and the meter's responses. A response alone contains no register address, so it cannot be decoded reliably.
- Publish raw serial bytes without conversion or framing wrappers.
- Disable retained messages and any heartbeat/registration bytes inserted into that stream.
- Use one publisher and one serial bus per topic. Wildcard topics are rejected to avoid mixing unrelated streams.
- Configure the gateway connection to remain passive on the bus. Disable unsolicited serial transmissions and MQTT-to-serial forwarding for the capture channel.

Exact gateway menu names depend on firmware. This integration does not configure or enforce the gateway's serial behavior. Hardware capture with your particular gateway/inverter combination still needs to be verified on your Home Assistant installation.

MQTT packets may contain part of a frame, a complete frame, or multiple frames; the integration retains a byte buffer between callbacks. Do not use a payload template or text decoder upstream.

## Sensors

39 meter sensors and 2 derived grid power sensors are registered under one Eastron meter device. A sensor starts **unavailable** until its register is observed. Unpolled sensors may remain unavailable permanently; disable those entities if desired.

| Reading | Zero-based starting register(s) | Unit | State class |
| --- | --- | --- | --- |
| L1/L2/L3 voltage | 0, 2, 4 | V | measurement |
| L1/L2/L3 current | 6, 8, 10 | A | measurement |
| L1/L2/L3 active power | 12, 14, 16 | W | measurement |
| L1/L2/L3 apparent power | 18, 20, 22 | VA | measurement |
| L1/L2/L3 reactive power | 24, 26, 28 | var | measurement |
| L1/L2/L3 power factor | 30, 32, 34 | unitless signed ratio | measurement |
| Average phase voltage | 42 | V | measurement |
| Average phase current | 46 | A | measurement |
| Sum of currents | 48 | A | measurement |
| Total active power | 52 | W | measurement |
| Total apparent power | 56 | VA | measurement |
| Total reactive power | 60 | var | measurement |
| Total power factor | 62 | unitless signed ratio | measurement |
| Frequency | 70 | Hz | measurement |
| Import / export active energy | 72, 74 | kWh | total_increasing |
| L1–L2 / L2–L3 / L3–L1 voltage | 200, 202, 204 | V | measurement |
| Average line-to-line voltage | 206 | V | measurement |
| Total active energy (import + export) | 342 | kWh | total_increasing |
| L1/L2/L3 import active energy | 346, 348, 350 | kWh | total_increasing |
| L1/L2/L3 export active energy | 352, 354, 356 | kWh | total_increasing |

Each value occupies **two consecutive 16-bit registers**. Address 0 here corresponds to the manual's input register 30001. Values are IEEE754 float32, **big-endian bytes and high word first**. Active power and power factor preserve their signs. Power factor `0.95` is a ratio, equivalent to 95%; Home Assistant can select its display unit. Invalid NaN/infinite floats and negative cumulative energy values are ignored.

Device classes match the physical quantities. The meter map follows the [Eastron SDM630MCT V1.7 protocol](https://www.eastroneurope.com/images/uploads/products/protocol/SDM630MCT_MODBUS_Protocol_V1.7.pdf); available measurements also depend on the meter wiring mode. Other SDM variants are not automatically detected.

## Availability and configuration

Use **Configure** on the integration to change the power sign, optionally create utility meters, or change the timeout from **1 to 86400 seconds**. The entry reloads cleanly when the option changes. To change the topic, remove the entry and add it with the new topic.

A correctly paired, CRC-valid response refreshes meter freshness. Each individual sensor also has its own freshness timer. Requests alone, CRC failures, exception responses, unpaired responses, and retained messages cannot keep stale readings available. MQTT disconnection immediately makes readings unavailable and clears partial frames; fresh traffic is required after reconnection.

Choose a timeout longer than the slowest register polling interval you want to observe. A request expires after five seconds; a longer request-to-response delay is not paired. Only one outstanding RTU request is tracked. A newer request replaces it.

## Solar and grid energy analysis

### Import and export power

Version 0.2 adds **Grid import power** and **Grid export power** in W. Both use the meter's signed **Total active power**, and only the active direction has a nonzero value.

Open **Settings → Devices & services → Solis SDM630 Sniffer → Configure** and set **Power sign for grid import**:

| Setting | Meter reading | Grid import power | Grid export power |
| --- | --- | --- | --- |
| Positive power means import (default) | +1500 W | 1500 W | 0 W |
| Positive power means import | −1500 W | 0 W | 1500 W |
| Negative power means import | −1500 W | 1500 W | 0 W |
| Negative power means import | +1500 W | 0 W | 1500 W |

You can change this setting at any time. It applies to these two power sensors only. The original signed power reading and lifetime energy counters remain untouched, as do all existing sensor IDs and history. The new sensors become unavailable when their source reading is stale; an unavailable source is never converted into zero consumption.

### Daily, monthly, and yearly utility meters

In the same **Configure** screen, select **Create daily, monthly and yearly import/export utility meters**, then save. This creates six standard Home Assistant [Utility Meter helpers](https://www.home-assistant.io/integrations/utility_meter/):

| Helpers | Source |
| --- | --- |
| Import energy daily / monthly / yearly | Meter **Import energy**, register 72 |
| Export energy daily / monthly / yearly | Meter **Export energy**, register 74 |

These are measured-energy totals from the meter's kWh counters, not estimates from sampled power. Both source entities must be enabled. Entity IDs are looked up in Home Assistant's registry, so renamed sensors work too.

The checkbox is a **one-time action** and clears after saving. Selecting it again reuses matching source/cycle helpers created through the UI (including by this action). YAML-defined utility meters are not detected; if you already use them, keep those and leave this checkbox off. It does not reset totals, recreate helpers on startup, or overwrite helpers you have customized. A retry after partial failure creates only the missing matching helpers. If you have existing helpers with different tariffs, offsets, or counter handling, those remain separate.

Find the created helpers under **Settings → Devices & services → Helpers**. They preserve their totals through restarts and use Home Assistant's local calendar for resets. The initial day/month/year is incomplete: accounting starts when the helper is created, with no historical backfill. Previous-period totals are exposed by the built-in helper. Sources are treated as lifetime counters with **Periodically resetting** disabled, so cumulative changes can be recovered after a temporary source outage. Negative counter corrections are not counted as negative consumption.

The helpers use the meter's original import/export counter directions. The power-sign setting does **not** swap their sources. If your meter's forward/reverse energy directions are opposite to physical grid import/export, map the appropriate counters in the Energy dashboard and adjust the helpers' names/sources yourself. Existing helpers are independently managed and are never deleted or retargeted automatically, including when this integration is removed.

### Energy dashboard and solar production

If the SDM630 measures your connection to the grid, configure **Settings → Dashboards → Energy** using:

| Energy dashboard role | Source |
| --- | --- |
| Grid consumption | Meter **Import energy** (kWh) |
| Return to grid | Meter **Export energy** (kWh) |
| Solar production | Your inverter's actual solar-production energy sensor, for example from SolisCloud |

Verify the meter's energy direction with known import/export conditions. Use the lifetime energy counters in the Energy dashboard; the daily/monthly/yearly helpers are optional for cards and automations. Do not add both a lifetime counter and its utility-meter helper to the same dashboard role, which would double-count energy.

A meter at the grid connection measures exchange with the grid. It cannot distinguish all solar generation from household consumption: solar used inside the home never crosses that connection. **Total energy** from this meter is **import + export**, not solar production or house consumption. Listening to the Solis-to-meter Modbus link does not add the inverter's own production readings to that stream.

For now, use your existing SolisCloud production sensor alongside the fully local grid readings. Fully local production requires a separate local source exposing the inverter's generation measurements. This integration remains passive and does not query the inverter. With a battery, configure its charge/discharge sources separately before interpreting household consumption or solar self-consumption.

## Diagnostics and troubleshooting

Download diagnostics from the integration's menu. They include frame counters, buffer size, pending request metadata, and sample ages. The topic is redacted, and raw payload history is not included.

For debug logging, enable debug logging in the integration menu or add:

```yaml
logger:
  default: warning
  logs:
    custom_components.solis_sdm630_sniffer: debug
```

Debug messages show decoded request ranges, decoded values, CRC failures, mismatched responses, and meter exceptions. Debug logs contain measurements; review them before sharing.

- **No requests decoded:** verify the exact topic, raw binary mode, and capture of the master's serial direction.
- **Requests but no paired responses:** verify capture of both directions, slave 1, function 0x04, and serial settings.
- **CRC failures:** check serial settings, interference, missing bytes, and gateway-added headers/heartbeats.
- **Only some sensors work:** the master may not poll the others, or the configured wiring mode may not expose them.
- **All sensors become unavailable:** inspect the MQTT connection and polling interval; increase the timeout if appropriate.

## Protocol limitations

This is a passive observer, not a Modbus master. CRC16 validation and structural checks reject damaged frames, but RTU carries **no transaction identifier**, and the MQTT stream lacks serial inter-byte timing. Lost, duplicated, reordered, or delayed traffic can make pairing ambiguous, particularly when two requests have equal response lengths. A CRC match cannot eliminate all possible ambiguity. Resynchronization deliberately drops pending pairing when stream confidence is lost.

The parser uses bounded buffering and rejects incomplete float pairs. It does not reconstruct a float from separate transactions. Register data from unsupported functions is not interpreted. Capturing all traffic in order is essential.

## Development and tests

Standalone tests run locally without Home Assistant:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

They cover CRC vectors/failures, fragmented and concatenated payloads, pairing, noise recovery, stale requests, exceptions, nonzero register offsets, float decoding, embedded frame-like data, bounded buffering, and the register map.

**Home Assistant compatibility tests run in GitHub Actions**, on Linux, against 2026.1.0 and 2026.9.3. They cover config/options flows, MQTT subscription arguments, sensors, timeouts, disconnects, setup/unload cleanup, and diagnostics. The local test collector omits `tests/ha` when Home Assistant is absent. No tests transmit Modbus requests.

## Removal

Remove the integration entry under **Settings → Devices & services**, then remove its download in HACS and restart Home Assistant. This does not modify the meter or gateway.

MIT licensed. Not affiliated with Solis, Eastron, PUSR, Home Assistant, or HACS.
