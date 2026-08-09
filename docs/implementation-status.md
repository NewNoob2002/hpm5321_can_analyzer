# Implementation Status

## Product firmware

The root firmware is currently a FreeRTOS/RTT/EasyLogger skeleton with an LED
idle task. It does **not** yet implement the USB-CAN protocol, vendor Bulk data
plane, MCAN service/task, queues or product CLI wiring. The Rust protocol,
device-session model, transport abstraction, fake backend and USB smoke tool
are implemented and tested, but are not yet a complete analyzer application.
A successful root build is only Gate A build evidence, not analyzer
functionality evidence.

The board overlay already maps SPI2 SD on PB10-PB13, card detect on PY00,
CAN1/MCAN0 LEDs on PY01/PY02, CAN2/MCAN2 LEDs on PY03/PA09 and STATUS on PA31.
Planning addendum `spi2-sd-led-2026-08-09` is approved and normalized. Product
firmware still has no `storage_task` and does not drive CAN activity LEDs; the
current idle-task STATUS writer must be retired when the health-owned indicator
service is introduced. P0S remains blocked on electrical/media/profile proof.
`scripts/phase0/storage_profile.py` makes the numeric and evidence requirements
executable; it intentionally rejects the checked-in BLOCKED evidence template.

## Phase 0 probes

Projects under `tools/phase0/` are isolated hardware-characterization firmware:

- `usb_hs_probe`: USB HS vendor-Bulk probe
- `mcan_internal_probe`: controller-only MCAN0/MCAN2 loopback
- `mcan0_external_probe`: MCAN0 listen-only and bounded Classic CAN traffic

Probe results reduce hardware risk but are not product-feature completion.

## Reproducibility boundary

The custom `hpm5321_custom` board overlay, dependency lock, probes, validators
and approved plans are tracked in Git; all shared CMake examples use
repository-relative `BOARD_SEARCH_PATH`. HPM SDK is an external dependency.
`dependencies/hpm-sdk.lock` pins official v1.12.1 commit `12bd9249...`; all
three standard presets have clean-build evidence at that exact commit in
`docs/evidence/phase1/T-DEV-001-003-official-sdk-clean-build-report.md`.
Historical hardware artifacts remain valid only for their recorded local-fork
revision and do not inherit the official-build identity.

## Phase 1B

Phase 1B is closed as `PASS` by
`docs/evidence/phase1/phase1b-closure-report.md`: reproducible firmware builds,
the J-Link GDB contract, the Rust host decision, Linux real USB and Windows
native CI/functional HIL are complete. Physical cable cycling stays in P3A
`T-USB-007`; Windows PnP/archive/package provenance stays in P6. OpenOCD was
not selected and macOS is deferred by the Linux/Windows CLI scope. These
downstream items are not represented as completed evidence.

The local Linux host toolchain is also closed: Rust/Cargo 1.97.1, GCC 16
ASan/UBSan, host tests and clippy pass. The physical P3A hotplug collector and
the stricter Windows PnP/provenance collector are ready, but their hardware and
Windows-native runs are not represented as PASS until their evidence bundles
exist.
