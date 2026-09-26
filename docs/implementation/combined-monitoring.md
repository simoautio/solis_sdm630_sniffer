# Combined local monitoring — implementation ledger

Authority: user-approved combined monitoring plan in the conversation, 2026-09-25.

Scope: optional read-only S2-WL-ST polling alongside passive MQTT; native inverter monitoring; fresh-source household balance; persisted estimated energy; selectable native Utility Meters; preserve existing identities. No inverter controls, cloud dependency, recorder changes, or battery support.

Topology: two independent paths. The PUSR USR-DR134 passively captures the existing Solis↔SDM630 RS485 bus (requests and responses) and publishes raw bytes to MQTT; it never transmits. The S2-WL-ST logger is actively polled over read-only Modbus TCP (function 04).

Reference: https://github.com/Pho3niX90/solis_modbus is used for polling ideas and register candidates only. Its register definitions must be validated against this inverter's firmware before use; its control and battery features are out of scope.

Defaults: port 502, unit 1, polling 30s (10–3600), timeout 5s, serial requests separated by 350ms, max 50 registers. Independent source failures. Household alignment <=5s. Native counters remain separate from estimated AC energy. No integration across outages/restarts.

Tasks: (1) TCP reader, profile and pure calculations; (2) independent logger runtime, persistence and entities; (3) options/helpers/diagnostics/docs; (4) tests, independent review and CI.

Baseline: 53 standalone tests passed. Home Assistant tests run in GitHub Actions only.
Live evidence: 11 logger cycles/5 minutes succeeded; MQTT subscription accepted but topic silent, inverter status 0x2011. Cloud confirmation and restored-meter acceptance remain pending.

Ruling: execute on feature/combined-local-monitoring in an isolated temporary worktree. User's implementation instruction approves the in-chat plan; no repeat design approval needed.
Ruling: preserve the SnifferRuntime as entry.runtime_data, adding an optional logger property. Existing sensor and diagnostics interfaces remain compatible.

Progress 2026-09-25: runtime wired into setup/unload (entry.runtime_data stays SnifferRuntime; runtime.logger optional); options flow (host/port/unit/interval, helper cycles/sources; existing helper checkbox kept); inverter + derived entities on device `{entry_id}_inverter`, unique ids `{entry_id}_inverter_{key}`; redacted diagnostics; README/CHANGELOG. Worktree moved to /Users/simo/Desktop/solis_sniffer-combined. Pending: CI green, live acceptance, v0.4.0.

Ruling 2026-09-26 (DR134/Solis Modbus plan): polling groups dropped. Snapshot-wide freshness would expire slow groups between reads, and the saving was ~3 of 9 reads per cycle. Extended telemetry dropped after a live read-only probe (function 04, logger 192.168.1.135). 33157 = 20 (×10 W = 200 W) matched 33079 active power 200 W but only duplicates it at coarser resolution. 33186–33189 read all zeros while 33169/33173 reported 364/32 kWh import/export, so those counters are not populated on this firmware.
