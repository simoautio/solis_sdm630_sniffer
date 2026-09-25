# Solis SDM630 Sniffer

[![Tests](https://github.com/simoautio/solis_sdm630_sniffer/actions/workflows/tests.yml/badge.svg)](https://github.com/simoautio/solis_sdm630_sniffer/actions/workflows/tests.yml)

A Home Assistant custom integration that **passively reads Eastron SDM630MCT meter traffic** captured by a PUSR USR-DR134 serial-to-MQTT gateway. Intended for an existing Solis-to-meter RS485 link.

At setup, choose what to monitor:

| Mode | What it does | Needs |
| --- | --- | --- |
| **Meter only** | Passively decodes SDM630 traffic from MQTT. It **never publishes MQTT messages, sends Modbus requests, or changes the meter**. | MQTT integration, RS485 gateway |
| **Inverter only** | [Reads the Solis inverter through its S2-WL-ST logger](#local-inverter-optional) over read-only Modbus TCP. | Logger on your network |
| **Meter and inverter** | Both, plus household power and consumption calculated from the two sources. | Both of the above |

Home Assistant's shared MQTT integration can independently publish its own birth/status messages.

## Requirements

- Home Assistant **2026.1 or later**.
- For the meter: the built-in **MQTT integration configured and enabled**, and:
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
6. Choose **What to monitor**: meter and inverter, meter only, or inverter only.
7. For the meter, enter the MQTT topic, availability timeout (default **60 seconds**) and update interval (default **30 seconds**).
8. For the inverter, enter the Solis logger's IP address (see [Local inverter](#local-inverter-optional)).

Each mode creates only the devices and entities it can populate. To switch an existing entry between meter-only/both and inverter-only, remove it and add it again; adding or removing the logger on a meter entry works any time under **Configure → Inverter logger**.

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

**Configure** on the integration opens a menu: **Meter** (power sign, availability timeout and update interval, each from **1 to 86400 seconds**), **Inverter logger**, and **Create utility meters**. The entry reloads cleanly when the option changes. To change the topic, remove the entry and add it with the new topic.

**Update interval** defaults to **30 seconds**, including existing installations without a saved setting. The integration still decodes every incoming MQTT message, but publishes only the latest readings at each interval. Dashboard values, automations, and Home Assistant history therefore update less often. Samples are not averaged, and intermediate readings are not replayed. Unchanged values need no new publication. Home Assistant manages history storage; this setting does not change Recorder configuration or the inverter’s polling rate.

Each sensor’s first valid reading, loss of availability, and recovery are reported immediately. Availability uses incoming sample timestamps independently of the update interval. Cumulative energy sensors still publish the meter’s latest lifetime totals.

A correctly paired, CRC-valid response refreshes meter freshness. Each individual sensor also has its own freshness timer. Requests alone, CRC failures, exception responses, unpaired responses, and retained messages cannot keep stale readings available. MQTT disconnection immediately makes readings unavailable and clears partial frames; fresh traffic is required after reconnection.

Choose a timeout longer than the slowest register polling interval you want to observe. A request expires after five seconds; a longer request-to-response delay is not paired. Only one outstanding RTU request is tracked. A newer request replaces it.

## Solar and grid energy analysis

### Import and export power

Version 0.2 adds **Grid import power** and **Grid export power** in W. Both use the meter's signed **Total active power**, and only the active direction has a nonzero value.

Open **Settings → Devices & services → Solis SDM630 Sniffer → Configure → Meter** and set **Power sign for grid import**:

| Setting | Meter reading | Grid import power | Grid export power |
| --- | --- | --- | --- |
| Positive power means import (default) | +1500 W | 1500 W | 0 W |
| Positive power means import | −1500 W | 0 W | 1500 W |
| Negative power means import | −1500 W | 1500 W | 0 W |
| Negative power means import | +1500 W | 0 W | 1500 W |

You can change this setting at any time. It applies to these two power sensors only. The original signed power reading and lifetime energy counters remain untouched, as do all existing sensor IDs and history. The new sensors become unavailable when their source reading is stale; an unavailable source is never converted into zero consumption.

### Utility meters

Open **Configure → Create utility meters**, choose the **cycles** (quarter-hourly, hourly, daily, monthly, yearly; default daily/monthly/yearly) and **sources** (meter import/export by default; Estimated solar/household energy when the logger is configured), then save. The defaults create six standard Home Assistant [Utility Meter helpers](https://www.home-assistant.io/integrations/utility_meter/):

| Helpers | Source |
| --- | --- |
| Import energy daily / monthly / yearly | Meter **Import energy**, register 72 |
| Export energy daily / monthly / yearly | Meter **Export energy**, register 74 |

These are measured-energy totals from the meter's kWh counters, not estimates from sampled power. Both source entities must be enabled. Entity IDs are looked up in Home Assistant's registry, so renamed sensors work too.

Submitting the page is a **one-time action**; nothing is stored for future startups. Submitting again reuses matching source/cycle helpers created through the UI (including by this action). YAML-defined utility meters are not detected; if you already use them, keep those and don't use this page. It does not reset totals, recreate helpers on startup, or overwrite helpers you have customized. A retry after partial failure creates only the missing matching helpers. If you have existing helpers with different tariffs, offsets, or counter handling, those remain separate.

Find the created helpers under **Settings → Devices & services → Helpers**. They preserve their totals through restarts and use Home Assistant's local calendar for resets. The initial day/month/year is incomplete: accounting starts when the helper is created, with no historical backfill. Previous-period totals are exposed by the built-in helper. Sources are treated as lifetime counters with **Periodically resetting** disabled, so cumulative changes can be recovered after a temporary source outage. Negative counter corrections are not counted as negative consumption.

The helpers use the meter's original import/export counter directions. The power-sign setting does **not** swap their sources. If your meter's forward/reverse energy directions are opposite to physical grid import/export, map the appropriate counters in the Energy dashboard and adjust the helpers' names/sources yourself. Existing helpers are independently managed and are never deleted or retargeted automatically, including when this integration is removed.

### Energy dashboard and solar production

If the SDM630 measures your connection to the grid, configure **Settings → Dashboards → Energy** using:

| Energy dashboard role | Source |
| --- | --- |
| Grid consumption | Meter **Import energy** (kWh) |
| Return to grid | Meter **Export energy** (kWh) |
| Solar production | Inverter **PV production total** or **Estimated solar energy** (see below), or a SolisCloud sensor — pick exactly one |

Verify the meter's energy direction with known import/export conditions. Use the lifetime energy counters in the Energy dashboard; the daily/monthly/yearly helpers are optional for cards and automations. Do not add both a lifetime counter and its utility-meter helper to the same dashboard role, which would double-count energy.

A meter at the grid connection measures exchange with the grid. It cannot distinguish all solar generation from household consumption: solar used inside the home never crosses that connection. **Total energy** from this meter is **import + export**, not solar production or house consumption. Listening to the Solis-to-meter Modbus link does not add the inverter's own production readings to that stream.

With a battery, configure its charge/discharge sources separately before interpreting household consumption or solar self-consumption. The calculated household values below assume **no battery**.

## Local inverter (optional)

Choose **Inverter only** or **Meter and inverter** when adding the integration and enter the S2-WL-ST logger's IP address, or add it later to a meter entry in **Configure → Inverter logger** (port 502, unit 1 and a 30 s polling interval by default; 10–3600 s). Leave it empty to disable polling.

- **Read-only**: only Modbus function 04 (read input registers) is implemented. Nothing is written to the inverter or logger, and logger settings and SolisCloud reporting are not changed. Requests are serialized, at most 50 registers each, at least 350 ms apart, over one short-lived connection per poll.
- Only model code `0x3306` (S6-EH3P 5–10K-H) is accepted; other models report `last_error: ModbusError` in diagnostics and stay unavailable.
- Entities live on a separate **Solis inverter** device. Meter entities, IDs and history are unchanged. A logger outage never affects meter availability and vice versa.
- After failed polls, retries back off up to five minutes. Stale values become **unavailable**, never zero.

| Entity | Source |
| --- | --- |
| PV DC power, PV1/PV2 voltage/current/power | Inverter registers (PV power = V × I) |
| L1/L2/L3 voltage and current, frequency, temperature, active/reactive/apparent power, grid port power, backup power | Inverter registers |
| PV production today / this month / this year / total (and previous periods) | Native inverter counters. **PV production total has 1 kWh resolution.** |
| Status; fault/status bits and model/firmware codes (shown as hex, e.g. `0x3306`); reported grid power, grid import/export and household values as seen by the inverter | Diagnostic |
| **Solar power** | Grid port power + backup power, never negative |
| **Household power** | Inverter AC delivery + net grid power (import positive, export negative). Needs a fresh meter sample within 5 s of the logger sample; otherwise unavailable. |
| **Estimated solar / household energy** (kWh) | Trapezoidal integration of the two power values. Persisted across restarts; gaps, outages and restarts are **not** bridged, so these are lower bounds. |
| Household balance status | Why household power is or isn't available (`ok`, `meter_unavailable`, `unaligned_samples`, …) |

For the Energy dashboard, keep the meter's **Import/Export energy** for the grid. For solar, use **either** the native **PV production total** (coarse but authoritative across outages) **or** **Estimated solar energy** (smooth, but misses outages) — never both. The **Reported grid import/export energy** counters are diagnostics only; the meter is authoritative for grid energy.

## Diagnostics and troubleshooting

Download diagnostics from the integration's menu. With a logger configured, a `logger` section shows the port, unit, poll failures, last error type, unsupported registers and value ages; the logger host is redacted. They also include traffic status, frame counters, buffer size, last/pending request metadata, and sample ages. The topic is redacted, and raw payload history is not included.

The `traffic_status` field describes recognized traffic within the configured availability timeout:

| Status | Meaning |
| --- | --- |
| `disconnected` | The integration is stopped or MQTT is disconnected. |
| `no_recent_requests_or_paired_responses` | No recent valid requests or matched responses have been decoded; this does not prove that MQTT is silent. |
| `requests_without_paired_responses` | Recent valid meter requests are arriving, but no recent matched response has been decoded. |
| `receiving_responses` | Recent requests and replies have been successfully matched; individual unpolled or invalid readings can still be unavailable. |

`requests_without_paired_responses` can appear briefly before the first reply. If it persists, inspect both directions of the serial capture, gateway topic routing, and the meter connection. It does not identify a wiring fault by itself. The `replaced_requests` counter counts valid requests that replaced an outstanding request before a matching reply was observed. A growing count can reveal missing replies even when frequent requests prevent the five-second request timeout from expiring. Counters accumulate until the entry reloads; recent traffic status and last-request metadata reset on MQTT reconnection.

A two-minute field capture contained 1,710 repetitions of a valid request for slave 1, function 04, starting at register 52 for 10 registers, with no replies. This proves those requests reach the MQTT topic, but supplies no measurements and does not establish the meter's normal polling coverage. With valid replies, that range includes total active, apparent, and reactive power. It does not include the cumulative energy counters; wait for a capture with working replies before drawing conclusions about other available sensors.

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
