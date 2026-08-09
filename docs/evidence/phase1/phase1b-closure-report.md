# Phase 1B Closure Report

Status: `PASS`  
Date: 2026-08-09  
Manifest: `docs/evidence/phase1/phase1b-closure.json`

## Closure Boundary

Phase 1B closes the reproducible development environment and host-stack
decision needed by P2 and P4P. It requires official-SDK firmware builds, shared
VSCode/CMake configuration, one working debug adapter, a selected host core,
native Linux/Windows host builds and one real vendor-Bulk functional lane on
both host families.

It does not absorb later product qualification. Physical cable cycling is
P3A/T-USB-007; the Windows PnP binding archive is P3A; signed/hash-addressed
release artifacts and installers are P6. Moving those tests to their owning
nodes is a gate-boundary correction, not a claim that they passed.

## Required Evidence

| Gate | Result | Evidence |
|---|---:|---|
| Official v1.12.1 three-preset clean build | PASS | `T-DEV-001-003-official-sdk-clean-build-report.md` |
| VSCode/CMake/clangd shared contract | PASS | development contract tests and checked-in presets/tasks |
| J-Link stop at `main`, inspect, step, reset | PASS | `T-DEV-005-jlink-gdb-report.md` |
| Rust single-core decision | PASS | `docs/development/adr-host-stack-spike.md` |
| Linux native host + real USB | PASS | `T-HOST-USB-LINUX-report.md` |
| Windows native build/test/clippy | PASS | GitHub run `30886654542`, `T-HOST-WINDOWS-CI-report.md` |
| Windows functional WinUSB/libusb HIL | PASS | `T-HOST-USB-WINDOWS-report.md` |

## Deferred Without False Closure

- Physical cable removal/reinsert: `NOT_TESTED`, owned by P3A/T-USB-007.
- Windows PnP binding output and release EXE provenance: `PARTIAL`, owned by
  P3A/P6. Functional device open/transfer/recovery already passed.
- OpenOCD: `NOT_SELECTED`; J-Link is the primary MVP debugger.
- macOS: deferred by the approved Linux/Windows CLI-first scope.

`python3 scripts/validate_phase1b_contract.py` is the deterministic closure
check. Any required evidence removal or status regression reopens Phase 1B.
