# Execution ledger — solis-sdm630-sniffer

Plan: docs/superpowers/plans/2026-09-24-solis-sdm630-sniffer.md

Ruling: Work in the supplied empty directory; it is not a Git repository, so worktree and commit scripts do not apply. Keep this durable ledger instead.
Pre-flight: protocol produces MeterUpdate.values keyed by zero-based register; runtime consumes that mapping; sensors consume runtime values with scaling from register descriptions. Config flow and runtime share topic/timeout constants. No interface conflicts.
Ruling: Use unitless native power factor (supported by HA 2026.1) to preserve the meter's signed ratio; this avoids unnecessary percent conversion.
Task 1: in progress — tests first.
Ruling: User explicitly prohibits Home Assistant installation on this Mac. The attempted install did not execute: .venv-ha contains only virtualenv bootstrap files. All Home Assistant tests will run in GitHub Actions, never locally. Python 3.13 was downloaded to temporary storage; it is not Home Assistant.
Task 1: 30 protocol tests passed. Register map has 39 supported measurements; replaced an erroneous guessed count assertion with the explicit planned address set.
Ruling: Parser emits complete aligned float pairs; runtime filters known register addresses. This keeps the standalone parser generic and avoids duplicate register maps.
Task 1: complete — 32 standalone tests passing after regression for an embedded CRC-valid frame inside a fragmented response. Wait for the expected response before searching inside its payload.
Tasks 2 and 3: implementation and HA tests written; real HA validation is delegated to GitHub Actions per explicit user instruction.
Task 4: packaging/README complete; public repository simoautio/solis_sdm630_sniffer explicitly authorized by user. Publication preparation underway.
