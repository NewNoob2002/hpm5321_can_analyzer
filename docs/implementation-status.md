# Implementation Status

## Product firmware

The root firmware now contains the first P2 RTOS ownership baseline: a statically
allocated `health_task`, queue and software timer; a stable high-low-high sampled
64-bit MCHTMR timebase; fault hooks; clock snapshots; and health-only LED writes.
It does **not** yet implement the USB-CAN data plane, MCAN owner tasks, protocol
wiring, hardware-watchdog feeding or product CLI. The Rust protocol,
device-session model, transport abstraction, fake backend and USB smoke tool
are implemented and tested, but are not yet a complete analyzer application.

The board overlay already maps SPI2 SD on PB10-PB13, card detect on PY00,
CAN1/MCAN0 LEDs on PY01/PY02, CAN2/MCAN2 LEDs on PY03/PA09 and STATUS on PA31.
Planning addendum `spi2-sd-led-2026-08-09` is approved and normalized. Product
firmware still has no `storage_task` and does not drive CAN activity LEDs from
CAN events; `health_task` is now the sole post-BSP LED writer and supplies the
STATUS heartbeat. P0S remains blocked on electrical/media/profile proof.
`scripts/phase0/storage_profile.py` makes the numeric and evidence requirements
executable; it intentionally rejects the checked-in BLOCKED evidence template.

## Phase 0 probes

Projects under `tools/phase0/` are isolated hardware-characterization firmware:

- `usb_hs_probe`: USB HS vendor-Bulk probe
- `mcan_internal_probe`: controller-only MCAN0/MCAN2 loopback
- `mcan0_external_probe`: MCAN0 listen-only and bounded Classic CAN traffic
- `spi_sd_probe`: read-only SPI2 SD detect, initialization, geometry and FAT32 probe
- `led_chaser`: one-at-a-time visual pin, polarity and routing check for all five LEDs

Probe results reduce hardware risk but are not product-feature completion.

## Phase 2

P2 remains `PARTIAL`. All three standard presets build without application
warnings. The baseline now includes static task/queue/timer ownership, a
fixed-capacity health/timer generation voter, a host-tested stable 64-bit
timebase, direct fault-hook injection, PLIC priority contracts, reset-source
snapshotting, and libc allocation counters frozen before scheduler start.

Target tests prove voter stall/missing/recovery, all three direct fault-hook
paths, zero post-freeze allocations and a clean 30-second heartbeat run with a
447-word health-task stack watermark. See
`docs/evidence/phase2/P2-RTOS-baseline-2026-08-09.md` and
`docs/evidence/phase2/P2-RTOS-followup-2026-08-09.md`.

P2 remains open for the actual 24-hour heartbeat qualification, an API-calling
product peripheral ISR target test, UART version/SDK/board/reset-cause logging,
and remaining operator LED evidence. The generation voter does not configure
or feed hardware WDG. USB and MCAN product owner tasks must not start before
the required P2 contracts close.

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
