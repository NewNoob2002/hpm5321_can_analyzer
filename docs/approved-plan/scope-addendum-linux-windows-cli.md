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

## Remaining Phase 1B gates

- Linux and Windows real vendor-Bulk enumeration, transfer and hotplug;
- Windows WinUSB binding and packaging/exit-code evidence;
- dependency and license manifest for Rust/libusb packaging;
- fake-backend parity remains a regression gate.

Formal protocol codec implementation begins only after these remaining USB and
packaging gates close. macOS evidence is rescheduled after the Windows CLI MVP.
