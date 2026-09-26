# DR134 documentation and Solis Modbus improvements implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clarify the PUSR USR-DR134 passive-sniffer architecture and add carefully scoped read-only monitoring improvements informed by the Solis Modbus Integration for Home Assistant.

**Architecture:** Keep the existing passive MQTT meter runtime and independent read-only Modbus TCP logger runtime. Improve logger polling by separating live, slow, and startup groups; add sustained-failure Repairs diagnostics; and expose a disabled-by-default extended telemetry group without changing household calculations or utility-meter sources.

**Tech Stack:** Python 3.13+, Home Assistant 2026.1+, pytest, Ruff, GitHub Actions, Markdown.

**Spec:** Existing design and implementation docs in `docs/superpowers/specs/2026-09-24-solis-sdm630-sniffer-design.md` and `docs/implementation/combined-monitoring.md`; upstream reference repository: https://github.com/Pho3niX90/solis_modbus.

## Global Constraints

- Keep the USR-DR134 path passive: it captures existing RS485 requests and responses and never publishes MQTT or transmits RS485.
- Keep the S2-WL-ST logger path read-only: Modbus function 04 only; no writes, control entities, or logger-setting changes.
- Preserve existing meter and inverter entity unique IDs, device identity, stored energy totals, utility-meter sources, and household-power semantics.
- Support the currently accepted model `0x3306`; unsupported models remain unavailable and must not be guessed into support.
- Do not add dependencies, battery-control features, SolisCloud API access, or live hardware assumptions.
- New extended telemetry is opt-in, diagnostic-only, and excluded from solar/household calculations and automatically created utility meters.

## Review Focus

- A slow or failed optional register block must not make healthy live sensors unavailable.
- Poll scheduling must not starve energy counters, repeatedly open unnecessary connections, or bridge integration gaps.
- A logger failure must create a clear Repairs issue only after sustained failures and clear it on recovery/unload.
- New register values must use correct signedness, scaling, state class, and unsigned 32-bit decoding.
- Documentation must distinguish DR134 passive capture from S2-WL-ST active read-only polling and must not claim unverified cloud behavior.

---

### Task 1: Document the DR134 passive-sniffer topology

**Status:** done (5349ef4).

**Files:**
- Modify: `README.md`
- Modify: `docs/implementation/combined-monitoring.md`
- Modify: `docs/superpowers/specs/2026-09-24-solis-sdm630-sniffer-design.md` only where the architecture wording is now stale.

**Interfaces:**
- Produces user-facing installation and troubleshooting wording; no Python API changes.

- [x] **Step 1: Write the documentation acceptance checklist**

The README must explicitly name the PUSR USR-DR134 as the passive sniffer and show these paths:

```text
Solis inverter ── existing RS485 bus ── SDM630MCT
                              │
                              └── USR-DR134 ── raw MQTT ── Home Assistant meter runtime

S2-WL-ST logger ── read-only Modbus TCP ── Home Assistant logger runtime
```

State that the DR134 listens to the existing bus, captures both master requests and meter responses, and must not be configured to poll, write, forward MQTT commands to RS485, or inject heartbeats into the capture stream.

- [x] **Step 2: Update the README**

Add a “Hardware and data flow” section, rename or clarify “Gateway setup” as “PUSR USR-DR134 passive sniffer setup,” link the official PUSR product/manual pages, and explain raw binary payloads, exact MQTT topics, serial settings, retained messages, and frame boundaries.

Add a short comparison explaining that the S2-WL-ST connection is separate and actively polled read-only. Replace any wording that implies sustained SolisCloud coexistence has already been proven with the verified limitation: no logger settings or cloud writes are made, while long-running cloud coexistence remains a site-acceptance check.

- [x] **Step 3: Update implementation documentation and review links**

Record the two-path topology, the DR134’s passive role, and the upstream repository’s useful ideas without copying control or battery-management features. Link https://github.com/Pho3niX90/solis_modbus and note that its register definitions are reference material requiring validation against this inverter firmware.

- [x] **Step 4: Verify documentation**

Run `rg -n -i "DR134|passive|S2-WL-ST|Modbus TCP|raw binary" README.md docs` and inspect the rendered Markdown sections for contradictory setup instructions.

- [x] **Step 5: Commit**

```bash
git add README.md docs
git commit -m "docs: explain DR134 passive meter capture topology"
```

### Task 2: Split logger polling into live, slow, and startup groups

**Status:** dropped — see ruling in `docs/implementation/combined-monitoring.md` (snapshot-wide freshness; ~3 reads saved).

**Files:**
- Modify: `custom_components/solis_sdm630_sniffer/inverter_registers.py`
- Modify: `custom_components/solis_sdm630_sniffer/logger_runtime.py`
- Modify: `custom_components/solis_sdm630_sniffer/const.py` and configuration strings only if a new fixed cadence needs to be surfaced.
- Test: `tests/ha/test_logger_runtime.py` and `tests/test_logger.py` where pure scheduling helpers are suitable.

**Interfaces:**
- Add immutable register group metadata with a cadence class: `startup`, `live`, or `slow`.
- Keep `LoggerRuntime.async_poll()` as the public polling entry point; it must continue publishing one coherent live snapshot and preserve existing derived calculations.

- [ ] **Step 1: Write failing tests**

Add tests proving that:

```python
assert startup_identity_reads == 1
assert live_groups_are_read_on_each_live_poll
assert slow_energy_groups_are_not_read_on_every_30_second_poll
assert slow_groups_are refreshed_after_the_slow_cadence
assert unsupported_slow_group_does_not_clear_live_values
```

Use a fake Modbus reader and a monotonic clock. Assert register addresses and call counts, not implementation details.

- [ ] **Step 2: Run the focused tests and verify expected failure**

Run `pytest tests/ha/test_logger_runtime.py -k "poll\|group\|cadence" -v` in the HA test environment or CI. The new tests must fail because all current `BLOCKS` are read every cycle.

- [ ] **Step 3: Define fixed cadence groups**

Keep identity `(33000, 4)` as startup/recovery/hourly, live power/status groups as live, and production/grid/household lifetime counters as slow with a fixed five-minute minimum cadence. Do not make the user-configured live interval shorter than the 350 ms request spacing or change the existing 10–3600 second validation range.

- [ ] **Step 4: Implement scheduling**

Track `last_group_read` by group name and select due groups per poll. Always retain the last successful values for groups not due, while marking values unavailable through the existing freshness/expiry rules when the logger itself is stale. Read identity on the first poll, after a failed poll recovers, and at most once per hour thereafter.

Optional-group failures must be isolated to that group. Preserve `_split_blocks`, `unsupported`, retry backoff, persistence checkpointing, and the existing no-zero-on-failure behavior.

- [ ] **Step 5: Run focused and existing tests**

Run `pytest tests/ha/test_logger_runtime.py tests/test_logger.py -v` in CI and confirm cadence, recovery, unsupported-group, energy, and existing protocol tests pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/solis_sdm630_sniffer tests/ha/test_logger_runtime.py tests/test_logger.py
git commit -m "feat: separate logger live and slow polling groups"
```

### Task 3: Add sustained logger failure Repairs diagnostics

**Status:** done; HA CI green on 2026.1.0 and 2026.9.3.

**Files:**
- Modify: `custom_components/solis_sdm630_sniffer/logger_runtime.py`
- Modify: `custom_components/solis_sdm630_sniffer/diagnostics.py`
- Modify: `custom_components/solis_sdm630_sniffer/strings.json` and `translations/en.json`
- Test: `tests/ha/test_logger_runtime.py`

**Interfaces:**
- Add a stable issue ID such as `logger_unreachable_<entry_id>`.
- Add a runtime success/failure counter and last-success timestamp to redacted diagnostics.

- [x] **Step 1: Write failing tests**

Test that five consecutive failed polls create one non-fixable error Repairs issue, a successful poll clears it, and unload clears it. Test that one failure does not create an issue and that diagnostics expose only error type, failure count, poll duration, and ages—not host, raw frames, or credentials.

- [x] **Step 2: Run tests to verify expected failure**

Run `pytest tests/ha/test_logger_runtime.py -k "repair\|failure\|diagnostic" -v`; expect missing issue behavior or missing fields.

- [x] **Step 3: Implement issue lifecycle**

Use `homeassistant.helpers.issue_registry` from the runtime. Create the issue after exactly five consecutive failures, clear on the next successful completed cycle, and clear during `async_stop()`. Keep the existing redacted diagnostics contract and do not include the configured host in issue placeholders unless the existing diagnostics privacy policy explicitly permits it; prefer the entry title and failure age.

- [x] **Step 4: Verify and commit**

Run the focused HA tests, then:

```bash
git add custom_components/solis_sdm630_sniffer tests/ha/test_logger_runtime.py
git commit -m "feat: report sustained logger failures as a repair"
```

### Task 4: Add opt-in extended read-only telemetry

**Status:** dropped — live probe: 33157 duplicates 33079; 33186–33189 read zero. See implementation ledger.

**Files:**
- Modify: `custom_components/solis_sdm630_sniffer/inverter_registers.py`
- Modify: `custom_components/solis_sdm630_sniffer/logger_runtime.py`
- Modify: `custom_components/solis_sdm630_sniffer/config_flow.py`
- Modify: `custom_components/solis_sdm630_sniffer/sensor.py`
- Modify: `custom_components/solis_sdm630_sniffer/strings.json` and `translations/en.json`
- Test: `tests/test_logger.py`, `tests/ha/test_config_flow.py`, and `tests/ha/test_logger_runtime.py`

**Interfaces:**
- Add `CONF_EXTENDED_TELEMETRY` with default `False`.
- Add three diagnostic register definitions:
  - `33157`: signed 16-bit, scale `10`, W, inverting/rectifying power.
  - `33186–33187`: unsigned 32-bit, kWh, AC grid-port lifetime energy fed out.
  - `33188–33189`: unsigned 32-bit, kWh, AC grid-port lifetime energy consumed.
- New entity unique IDs must follow the existing `{entry_id}_inverter_{key}` pattern and use the existing inverter device.

- [ ] **Step 1: Write failing tests**

Test unsigned decoding above `2^31`, signed/scaled `33157`, default-disabled configuration, enabled entity creation, optional block failure isolation, and exclusion from household/solar calculations and utility-meter source selection.

- [ ] **Step 2: Run focused tests and verify expected failure**

Run `pytest tests/test_logger.py tests/ha/test_config_flow.py tests/ha/test_logger_runtime.py -k "extended\|33157\|33186\|33188" -v` and confirm the new definitions/options/entities are absent.

- [ ] **Step 3: Add definitions and configuration**

Add the register metadata with diagnostic entity category and no automatic utility-meter source entries. Add a Configure toggle with a conservative default of disabled. Preserve existing options for older entries and reload behavior.

- [ ] **Step 4: Add optional polling**

Read the extended power register in the live cadence and extended lifetime counters in the slow cadence only when enabled. An illegal-address response marks only that key unsupported. Do not include these values in `combined_power()` or estimated-energy integration.

- [ ] **Step 5: Verify and commit**

Run focused tests and commit:

```bash
git add custom_components/solis_sdm630_sniffer tests
git commit -m "feat: add opt-in extended inverter telemetry"
```

### Task 5: Full validation and deployment handoff

**Status:** local checks and CI done; changelog updated. Awaiting review before merge.

**Files:**
- Modify: `CHANGELOG.md` only after all tests pass.
- Review: all changed files and generated Home Assistant translations.

- [x] **Step 1: Run local checks**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv-ha/bin/python -m compileall -q custom_components
.venv/bin/pytest -q
```

- [x] **Step 2: Run CI compatibility matrices**

Push the branch and require both Home Assistant matrix jobs (2026.1.x and the current supported 2026.x version) plus standalone CI to pass. Home Assistant tests are not run locally by project policy.

- [ ] **Step 3: Review documentation and behavior**

Confirm the DR134 wording is accurate, extended telemetry is visibly opt-in, issue diagnostics are redacted, existing entity IDs are unchanged, and the Energy Dashboard guidance still prefers the authoritative meter counters for grid energy.

- [x] **Step 4: Update changelog and commit**

Add an Unreleased entry describing DR134 documentation, logger polling groups, sustained-failure Repairs, and opt-in telemetry. Do not claim hardware validation for unverified registers.

- [ ] **Step 5: Deploy**

After CI passes and review finds no critical or important issues, push the implementation branch to GitHub. Do not publish a release or enable new telemetry automatically on existing entries.

## Assumptions and decisions

- The passive sniffer hardware is specifically the PUSR USR-DR134, not the S2-WL-ST. The DR134 is a bidirectional serial gateway by product design, but this integration uses it only as a listener/capture path.
- Five minutes is the fixed minimum cadence for slow energy-counter groups; live polling keeps the user-configured interval.
- Five consecutive logger failures trigger Repairs, matching the upstream integration’s sustained-failure approach.
- The upstream repository is used as a reference for polling and register candidates, not as a source of control features or unvalidated model support.
- New telemetry remains diagnostic-only until confirmed on the target S6-EH3P10K-H firmware.
