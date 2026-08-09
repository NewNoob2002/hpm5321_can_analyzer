# Scope Addendum — Linux/Windows CLI First

Date: 2026-08-03  
Authority: user review update; overrides conflicting host-platform/Qt timing in
the approved PRD while preserving all non-conflicting protocol and safety gates.

## Decision

1. MVP host delivery targets Linux and Windows CLI first.
2. macOS is deferred and does not block the MVP or current host-stack gate.
3. The shared host core and CLI use Rust. The passing Phase 1B Rust synthetic,
   reconnect and process-recovery lane is the baseline.
4. Qt is not a CLI dependency. Qt 6 licensing, deployment and GUI selection are
   deferred to the 1.0 GUI phase.
5. A future Qt GUI may consume the single Rust host core through a reviewed
   boundary; it must not introduce a second protocol/USB core.

## Phase 1B Closure

Phase 1B closure: `PASS` on 2026-08-09. The official SDK build, selected
J-Link adapter, Rust core, fake-backend parity, Linux real vendor-Bulk lane,
Windows native CI and Windows functional vendor-Bulk HIL are complete. Protocol
and device session implementation that already landed is valid P4P progress;
it is no longer described as prohibited or pending on packaging.

Physical cable cycling remains P3A/T-USB-007. Windows PnP binding capture is a
P3A evidence item, while release EXE hashes, dependency/license bundle and
installer packaging remain P6. Those items keep their own `PARTIAL` or
`NOT_TESTED` states and are not implied by Phase 1B closure. macOS remains
deferred for the current Linux/Windows CLI scope.
