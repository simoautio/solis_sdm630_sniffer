# Solis SDM630 Sniffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if selected by the user. Steps use checkbox syntax for tracking.

**Goal:** Deliver a tested, passive, HACS-installable binary-MQTT SDM630MCT integration.

**Architecture:** A dependency-free stream parser produces validated register updates. A config-entry-owned push runtime subscribes to MQTT, tracks freshness, and notifies native sensors. Configuration, diagnostics, and packaging remain separate from protocol parsing.

**Tech Stack:** Python, Home Assistant 2026.x public APIs, pytest, and HACS custom repository packaging.

**Spec:** `docs/superpowers/specs/2026-09-24-solis-sdm630-sniffer-design.md`

## Global Constraints

- Domain: `solis_sdm630_sniffer`; default exact topic: `solis/rs485/raw`.
- Built-in MQTT dependency; subscription uses `encoding=None`.
- Never publish MQTT or issue Modbus requests.
- Slave 1, function 0x04, CRC16 verification, big-endian IEEE754 floats.
- Default availability timeout: 60 seconds; request pairing timeout: 5 seconds.
- MQTT callbacks may contain partial frames or multiple frames.
- Ignore retained messages; no historical payload establishes live availability.
- Use typed `ConfigEntry.runtime_data` and asynchronous platform lifecycle.
- Do not fabricate GitHub ownership or repository URLs.

## Review Focus

1. A response can resemble an eight-byte request: test competing candidates and preserve incomplete frames.
2. A corrupt frame can precede a valid transaction in the same payload: verify bounded recovery and no stale pairing.
3. Sparse polling can leave individual sensors stale while meter traffic continues: test per-register expiration.
4. MQTT disconnects can leave partial frames and pending requests: reset parser state on disconnect and require fresh samples after reconnect.
5. A setup failure after subscription can leak callbacks: exercise failure cleanup as well as normal unload.

## File Structure

`custom_components/solis_sdm630_sniffer/` contains `__init__.py` (entry lifecycle), `const.py` (defaults), `protocol.py` (parser), `registers.py` (meter map), `runtime.py` (subscription and freshness), `sensor.py` (entities), `config_flow.py` (UI), `diagnostics.py`, `manifest.json`, `strings.json`, and `translations/en.json`.

`tests/` contains pure protocol tests, register tests, and a separate Home Assistant test directory with its fixtures. Root files include `README.md`, `LICENSE`, `hacs.json`, `pyproject.toml`, development requirements, `.gitignore`, and `.github/workflows/tests.yml`.

## Task 1: Stream decoding and register map

**Files:** `protocol.py`, `registers.py`, `tests/test_protocol.py`, `tests/test_registers.py`, and pytest configuration.

**Interfaces:** `crc16(data: bytes) -> int`; `StreamParser.feed(payload: bytes, now: float) -> list[MeterUpdate]`; `StreamParser.reset() -> None`; `MeterUpdate.values: dict[int, float]`. Parser exposes counters and pending-request metadata for diagnostics. Register descriptions contain address, key, name, unit, device class, state class, and scale.

- [ ] Write independent CRC and frame fixtures. Use `bytes.fromhex("01040000000271cb")` as the known request; CRC value is `0xCB71`. Construct response payloads with `struct.pack(">f", value)` and append the CRC in little-endian order.

```python
def test_known_crc():
    assert crc16(bytes.fromhex("010400000002")) == 0xCB71


@pytest.mark.parametrize("cut", range(1, 17))
def test_fragmentation(cut):
    stream = bytes.fromhex("01040000000271cb") + response(230.5)
    parser = StreamParser()
    updates = parser.feed(stream[:cut], now=0)
    updates += parser.feed(stream[cut:], now=0.1)
    assert [update.values for update in updates] == [{0: 230.5}]
```

- [ ] Run `python -m pytest tests/test_protocol.py -q`; confirm failure because parser implementation is missing.
- [ ] Implement CRC and immutable request/update records. The parser retains an incomplete suffix, uses CRC and structural validation to distinguish candidates, and consumes all complete frames. Limit retained data to 4096 bytes; process large payloads incrementally so the limit does not discard legitimate concatenated transactions.
- [ ] Implement request replacement, expiration, exception handling, matching byte counts, and corruption reset. Nonmatching or unsolicited responses produce no update. Bound a request to 1–125 registers and a valid 16-bit address range. Decode only known pairs completely inside the requested range, without joining different responses.
- [ ] Define the initial supported zero-based map: phase voltages 0/2/4, currents 6/8/10, active power 12/14/16, apparent power 18/20/22, reactive power 24/26/28, power factors 30/32/34; average voltage 42, average current 46, sum current 48, total powers 52/56/60, total power factor 62, frequency 70, import/export kWh 72/74, line voltages 200/202/204 and average 206, total kWh 342, per-phase import kWh 346/348/350 and export kWh 352/354/356. Verify these against Eastron V1.7 before implementation. All instantaneous readings are measurements; nonnegative cumulative kWh counters are total-increasing. Convert power factor to percent.
- [ ] Add concatenated transactions, byte-at-a-time input, bad CRC, noise recovery, other slave addresses, response/request ambiguity, changed requests, wrong byte count, exceptions, timeouts, nonzero addresses, incomplete pairs, NaN/infinity, and buffer-limit tests.

```python
def test_unsolicited_response():
    assert StreamParser().feed(response(230.5), now=0) == []


def test_expired_request():
    parser = StreamParser()
    parser.feed(bytes.fromhex("01040000000271cb"), now=0)
    assert parser.feed(response(230.5), now=6) == []
```

- [ ] Run all pure tests; confirm CRC debug logging does not mistake partial candidates for conclusively corrupt frames. Commit if this workspace has become a Git repository; otherwise preserve files without initializing Git solely for process bookkeeping.

## Task 2: Home Assistant runtime and sensors

**Files:** `__init__.py`, `const.py`, `runtime.py`, `sensor.py`, `manifest.json`, and `tests/homeassistant/test_runtime.py` / `test_sensor.py`.

**Interfaces:** `SnifferRuntime.async_start()`, `async_stop()`, `async_add_listener(callback) -> unsubscribe`, `values`, and `is_available(address)`. Inject or patch monotonic time for deterministic expiration tests. Typed config entries hold this runtime.

- [ ] Write failing tests that capture the subscription callback, inject the known request/response, and assert native sensor state and metadata. Patch publishing APIs to fail if called.

```python
subscribe.assert_awaited_once_with(
    hass,
    "solis/rs485/raw",
    runtime.async_message_received,
    qos=0,
    encoding=None,
)
assert sensor.native_value == pytest.approx(230.5)
assert sensor.native_unit_of_measurement == "V"
assert sensor.available
```

- [ ] Implement MQTT subscription and connection-status listener using public APIs. Parse only binary, non-retained payloads. No publication or Modbus client dependencies are present.
- [ ] Store latest values and timestamps per register plus last valid paired response. Notify entities on changed values and availability transitions. Schedule expiration with Home Assistant event helpers and cancel previous timers before rescheduling. Disconnect clears stream state and availability; reconnect waits for fresh meter data.
- [ ] Add entity descriptions, stable IDs based on config entry/register, shared `DeviceInfo`, native metadata, and listener removal. Entities never poll and never fabricate initial zero values.
- [ ] Add tests for retained traffic, individual freshness, silent MQTT expiration, recovery, ignored exceptions, options reload cleanup, setup failure after subscription, and unload. Include partial-frame disconnect/reconnect so old bytes cannot combine with a new session.

```python
clock.advance(61)
runtime.async_check_expiry()
assert not sensor.available
unsubscribe.assert_called_once()
```

- [ ] Run the Home Assistant tests in a compatible Python environment. Local discovery found Python 3.9 and 3.11 only; create a supported environment when available or run the full suite in CI and explicitly report local limitations. Do not substitute mocked Home Assistant packages for a real compatibility run.

## Task 3: UI configuration and diagnostics

**Files:** `config_flow.py`, `diagnostics.py`, `strings.json`, `translations/en.json`, `tests/homeassistant/test_config_flow.py`, and `test_diagnostics.py`.

**Interfaces:** UI entry data stores `topic` and `timeout`; options override `timeout`. Diagnostics read runtime state without subscribing or accessing raw payload history.

- [ ] Write failing tests for default form, valid entry creation, duplicate exact topic, missing MQTT, wildcard/empty/null-character topics, invalid timeout, and options reload.

```python
result = await hass.config_entries.flow.async_init(
    DOMAIN,
    context={"source": "user"},
    data={"topic": "solis/rs485/raw", "timeout": 60},
)
assert result["type"] == FlowResultType.CREATE_ENTRY
assert result["data"]["topic"] == "solis/rs485/raw"
```

- [ ] Implement MQTT prerequisite handling without sending probe traffic. Validate a single topic using public MQTT topic validation plus explicit wildcard rejection. Validate finite positive timeout and use a number selector. Duplicate identity is the exact topic; avoid silently stripping meaningful spaces from MQTT topics.
- [ ] Implement timeout options flow and asynchronous reload listener. Add matching English strings for every form label, error, and abort reason.
- [ ] Implement downloadable diagnostics with counts, pending metadata, buffer size, and ages. Redact topic; do not return message payloads or entity/config entry identifiers unnecessarily.

```python
diagnostics = await async_get_config_entry_diagnostics(hass, entry)
assert "solis/rs485/raw" not in json.dumps(diagnostics)
assert diagnostics["parser"]["buffer_size"] >= 0
```

- [ ] Run flow, runtime, and diagnostics tests together; verify reload does not duplicate subscriptions.

## Task 4: Packaging, documentation, and release verification

**Files:** `hacs.json`, `README.md`, `LICENSE`, `.gitignore`, development requirements, `.github/workflows/tests.yml`, and completed manifest metadata.

- [ ] Add HACS integration metadata and a versioned manifest with MQTT dependency and empty third-party runtime requirements. Use real available project documentation metadata; describe the need to publish to the user's actual GitHub repository for HACS custom-repository installation. Do not claim HACS default-store acceptance.

```json
{
  "name": "Solis SDM630 Sniffer",
  "homeassistant": "2026.1.0"
}
```

- [ ] Write manual installation instructions for `custom_components/solis_sdm630_sniffer`, restart, configure built-in MQTT, add this integration, and select topic/timeout. Explain HACS custom-repository installation using the actual published repository URL.
- [ ] Document gateway requirements: raw binary transparent forwarding, both serial directions, ordered single stream, matching serial settings, retained messages disabled, and no injected heartbeat/registration bytes. Explain unavailable sensors when the existing master never requests their registers.
- [ ] Include supported register addresses, float order, timeout behavior, passive-only limitations, and logger YAML. Link official Home Assistant documentation and the Eastron protocol source. Note that Home Assistant's shared MQTT integration may independently publish its own lifecycle messages; this custom integration does not publish.
- [ ] Add CI jobs for pure tests and real Home Assistant tests using a compatible Python version, plus syntax/lint and manifest/translation JSON checks. Test the declared minimum supported Home Assistant version and a current available 2026.x version; do not infer future version availability from the current date.
- [ ] Run all available checks, inspect the full diff, and search integration code for MQTT publication and active Modbus calls. Review the five focus cases above. Report exact passing checks and any compatibility or hardware validation not performed.

## Plan Review

Spec coverage: all requested components, tests, passive constraints, packaging, and documentation are assigned above. No product code has been written yet. Native execution is recommended because the parser/runtime interfaces are closely coupled and the scope fits one implementation session.
