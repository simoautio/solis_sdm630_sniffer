# Solis SDM630 sniffer design

## Intended outcome

Create `solis_sdm630_sniffer`, a HACS-installable Home Assistant 2026.x custom integration that turns passively captured SDM630MCT Modbus RTU traffic into native sensors. The PUSR USR-DR134 publishes raw binary bytes, including both requests and responses, in order on one MQTT topic. MQTT message boundaries are not serial frame boundaries.

The integration never publishes MQTT messages and never transmits serial or Modbus requests. Only measurements already polled by the existing Modbus master can become available.

## Approach

Use a standalone Python stream parser, a Home Assistant push-update runtime, and native sensor entities. This makes protocol handling independently testable without starting Home Assistant.

Alternatives considered: putting parsing directly in the MQTT callback couples protocol tests to Home Assistant; a general Modbus client library introduces unnecessary active-client machinery and does not solve passive request/response correlation. The standalone parser is recommended.

## Configuration and lifecycle

- Domain and folder: `custom_components/solis_sdm630_sniffer`.
- Manifest declares `mqtt` dependency, config flow, version, and local-push I/O.
- UI configuration accepts a single exact MQTT topic (default `solis/rs485/raw`) and availability timeout (default 60 seconds, configurable positive seconds). Reject wildcard topics to prevent interleaving independent streams. Prevent duplicate entries for the same topic.
- An options flow changes the timeout; configuration reloads cleanly.
- Store the typed runtime in `ConfigEntry.runtime_data`. Forward sensor setup using the current asynchronous config-entry APIs.
- Subscribe through Home Assistant's MQTT API using `encoding=None`. Ignore retained messages because historical bytes cannot establish live availability.
- Register cleanup for subscriptions, listeners, and timers on unload and setup failure.

## Stream parser

- Maintain a bounded byte buffer across callbacks. Iterate until no complete candidate frame remains, preserving incomplete suffixes.
- Verify standard Modbus CRC16 (initial value 0xFFFF, polynomial 0xA001, low CRC byte first).
- Recognize slave 1 function 0x04 requests (8 bytes), responses (byte-count plus 5 bytes), and exception responses (5 bytes).
- Validate request range and quantity, response byte count, and CRC before accepting a frame. Handle noise and corrupt data by resynchronizing to plausible CRC-valid frames. Record failures without logging warnings for normal fragmentation.
- Keep one outstanding request, including its starting register, quantity, and monotonic timestamp. A newer valid request replaces the older one. Require matching response byte count; unsolicited responses never acquire an invented register address.
- Expire pending requests after 5 seconds; clear pairing on exceptions and detected stream corruption. The parser must never stitch incomplete floats from different transactions together.
- Decode known, fully covered register pairs as big-endian IEEE754 floats with high word first. Reject NaN and infinity. Ignore unsupported registers.
- Explain inherent limitations: Modbus RTU has no transaction identifier, and MQTT carries no inter-byte timing. Lost or reordered traffic and late equal-length responses can make correlation ambiguous. CRC alone cannot remove that ambiguity.

## Sensors and availability

Use a centralized register description table based on the Eastron SDM630MCT V1.7 protocol. Cover per-phase voltage, current, active/apparent/reactive power and power factor, aggregate power/current/voltage, frequency, line-to-line voltage, and import/export energy counters where documented. Publish an explicit supported-register table in the README; never infer meter variants from bytes.

Each entity has a stable entry/register unique ID, a shared device identifier, native unit, suitable device class, and measurement or total-increasing state class as appropriate. Power factor is converted to percent if required by Home Assistant's power-factor class. Signed active power remains signed.

Entities start unavailable until their own value is decoded. A correctly paired, CRC-valid meter response refreshes meter freshness; requests, malformed frames, retained traffic, and exception responses do not. A timer makes entities unavailable when meter freshness expires, even when MQTT is silent. Sensor freshness is also tracked so values from registers no longer polled cannot remain indefinitely available merely because other registers are updated.

## Diagnostics

Debug logs identify accepted requests, register ranges, decoded responses, mismatches, exceptions, and CRC failures. Downloadable diagnostics expose parser counters, buffer length, pending request metadata, and freshness information. Redact the configured MQTT topic and omit raw payload history.

## Repository and installation

Include `hacs.json`, versioned integration manifest, config flow strings and English translations, README, license, pytest configuration, and CI. The README covers HACS custom-repository installation after publishing this repository, manual installation, MQTT prerequisite, transparent binary gateway operation, passive capture of both directions, configuration, logging, and limitations. Do not invent a GitHub repository owner; publication-specific metadata must use the actual destination when available.

## Verification

Protocol pytest coverage includes an independently known CRC vector, invalid CRC, all fragmentation boundaries, one-byte chunks, concatenated transactions, request replacement, unpaired responses, mismatched byte counts, exceptions, stale requests, noise recovery, buffer limits, nonzero register offsets, signed floats, and nonfinite floats.

Home Assistant tests cover config flow validation and duplicates, binary MQTT subscription, sensor metadata/value updates, availability expiration and recovery, retained messages, options reload, and unload cleanup. Verify no publishing API or active Modbus client exists. Run protocol tests locally and Home Assistant tests in a supported Python environment; report any environment limits explicitly.

## Reference sources

- Home Assistant runtime data: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/
- Home Assistant MQTT implementation: https://github.com/home-assistant/core/blob/dev/homeassistant/components/mqtt/client.py
- Eastron SDM630MCT V1.7: https://eastroneurope.com/images/uploads/products/protocol/SDM630MCT_MODBUS_Protocol_V1.7.pdf

## Review status

Design prepared for user review. Implementation has not started. The workspace is empty and is not yet a Git repository.
