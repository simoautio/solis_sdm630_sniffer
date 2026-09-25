# Combined local monitoring — implementation ledger

Authority: user-approved combined monitoring plan in the conversation, 2026-09-25.

Scope: optional read-only S2-WL-ST polling alongside passive MQTT; native inverter monitoring; fresh-source household balance; persisted estimated energy; selectable native Utility Meters; preserve existing identities. No inverter controls, cloud dependency, recorder changes, or battery support.

Defaults: port 502, unit 1, polling 30s (10–3600), timeout 5s, serial requests separated by 350ms, max 50 registers. Independent source failures. Household alignment <=5s. Native counters remain separate from estimated AC energy. No integration across outages/restarts.

Tasks: (1) TCP reader, profile and pure calculations; (2) independent logger runtime, persistence and entities; (3) options/helpers/diagnostics/docs; (4) tests, independent review and CI.

Baseline: 53 standalone tests passed. Home Assistant tests run in GitHub Actions only.
Live evidence: 11 logger cycles/5 minutes succeeded; MQTT subscription accepted but topic silent, inverter status 0x2011. Cloud confirmation and restored-meter acceptance remain pending.

Ruling: execute on feature/combined-local-monitoring in an isolated temporary worktree. User's implementation instruction approves the in-chat plan; no repeat design approval needed.
Ruling: preserve the SnifferRuntime as entry.runtime_data, adding an optional logger property. Existing sensor and diagnostics interfaces remain compatible.
