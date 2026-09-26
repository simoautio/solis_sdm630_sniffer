# Logger reliability implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement these fixes inline.

**Goal:** Fix the three reviewed regressions and push the verified result to GitHub.
**Architecture:** Keep the current runtime and config-entry identities. Coalesce storage requests without moving an outstanding deadline, reschedule per-register expiry, and validate logger endpoints across all entries.
**Tech Stack:** Python, Home Assistant, pytest, GitHub Actions.
**Spec:** The three findings in the preceding review, authorized by “fix it”; GitHub deployment explicitly authorized.

## Global constraints
- Keep Modbus read-only and MQTT passive.
- Preserve existing meter and inverter unique IDs and energy history.
- Run Home Assistant tests in GitHub Actions only, per project handover.
- Do not publish a release or touch live hardware.

## Review focus
- Repeated successful polls must checkpoint before graceful shutdown.
- The next checkpoint must contain newer totals, not only the first snapshot.
- Expiring one group must not strand another group or leave orphan timestamps.
- Duplicate checks must include combined entries and Configure, excluding self.
- Defaults and hostname case must match; different ports/unit IDs remain distinct.

## Tasks
- [x] Add failing HA regressions for persisted totals under continuous polling, successive expiry deadlines, cross-mode duplicate setup, and duplicate Configure with retry.
- [x] Push a test branch and confirm expected failures in CI.
- [x] Guard outstanding delayed saves with a pending flag cleared when the data callback runs; retain stop-time save.
- [x] Extract expiry scheduling, call it after polls and expiry callbacks, and remove timestamps together with invalidated derived values.
- [x] Compare normalized (host, port, unit) tuples against current entry options in setup and Configure; return an abort on duplicate setup and a retryable field error in Configure. Preserve existing IDs.
- [x] Run standalone tests, lint, format, compilation, and both HA CI matrices; independently review changes.
- [x] Update changelog, fast-forward main, and push the verified result to GitHub.

Ruling: proceed inline without another plan approval because the user explicitly authorized the concrete fixes. Use an isolated temporary worktree and a dedicated CI branch. Baseline: 69 standalone tests pass.

Verification 2026-09-26: regression-only CI 36179148360 reproduced the faults; fixed commit 381ed6e passed standalone and Home Assistant 2026.1.0 / 2026.9.3 in CI 36210568332. Both HA matrices: 149 passed each. Local standalone: 69 passed; Ruff and Python 3.13 compilation passed. Independent review found no important issues. Changelog updated; GitHub main deployment follows this documentation commit.
Ruling: logger-only config-entry endpoint IDs now include host, port and unit, and change atomically with options to avoid duplicate reloads. Existing entity/device/storage identities remain based on unchanged entry_id.
