# Implementation Status

## Product firmware

The root firmware contains the P2 RTOS ownership baseline, the first P3A USB
vertical slice and the P3B MCAN0 listen-only software slice: statically
allocated `health_task`, USB owner and MCAN0 owner tasks, bounded queues/ring
and software timer; a stable high-low-high sampled 64-bit MCHTMR timebase;
fault hooks; clock snapshots; health-only LED writes; raw vendor Bulk echo; and
timestamped Classic-CAN RX publication with explicit loss/error diagnostics.
It does **not** yet implement the USB-CAN data plane, protocol wiring,
authorized product TX, hardware-watchdog feeding or product CLI.
The Rust protocol,
device-session model, transport abstraction, fake backend and USB smoke tool
are implemented and tested, but are not yet a complete analyzer application.

The board overlay already maps SPI2 SD on PB10-PB13, card detect on PY00,
CAN1/MCAN0 LEDs on PY01/PY02, CAN2/MCAN2 LEDs on PY03/PA09 and STATUS on PA31.
Planning addendum `spi2-sd-led-2026-08-09` is approved and normalized. Product
firmware still has no `storage_task` and does not drive CAN activity LEDs from
CAN events; `health_task` is now the sole post-BSP LED writer and supplies the
STATUS heartbeat. The MCAN0 owner now signals accepted RX activity to
`health_task`, which pulses CAN1 RX while preserving sole GPIO-writer
ownership; CAN1 TX remains off because product TX is disarmed. P0S remains
blocked on electrical/media/profile proof.
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

## Phase 3B

P3B is `PARTIAL`. The product build now has a long-running static MCAN0 owner
at 1 Mbit/s Classic CAN, initialized listen-only before the pads are connected.
It drains RXFIFO0 through a bounded ISR queue into a 64-record timestamped
consumer ring, records queue/ring loss separately, snapshots error state, votes
the watchdog and never performs automatic bus-off recovery. Its TX entry point
is present only as a fail-closed boundary and always rejects while disarmed.

The software/build boundary is recorded in
`docs/evidence/phase3/P3B-MCAN0-software-baseline-2026-08-12.md`. P3B still
needs product-image target/listen-only proof, external RX/timing correlation,
the 30-minute `BP-CAN-MVP-v1` run and bounded bus-off policy evidence. Protocol
arm/expiry/rate admission, TX result/cancel and USB disconnect/reset disarm
belong to the P4E integration step and must land before product TX is enabled.

## Phase 2

P2 remains `PARTIAL`. All three standard presets build without application
warnings. The baseline now includes static task/queue/timer ownership, a
fixed-capacity health/timer generation voter, a host-tested stable 64-bit
timebase, direct fault-hook injection, PLIC priority contracts, reset-source
snapshotting, and libc allocation counters frozen before scheduler start.

Target tests prove voter stall/missing/recovery, all three direct fault-hook
paths, zero post-freeze allocations and a clean 30-second heartbeat run with a
447-word health-task stack watermark. UART0 startup logging now reports the
firmware version, SDK revision, board revision and decoded reset cause; the
UART-enabled image is target-running, and a 447-byte physical capture closes
`T-BSP-001` as `PASS`. See
`docs/evidence/phase2/P2-RTOS-baseline-2026-08-09.md` and
`docs/evidence/phase2/P2-RTOS-followup-2026-08-09.md` plus
`docs/evidence/phase2/T-BSP-001-uart-banner-2026-08-09.md`.

P2 remains open for the actual 24-hour heartbeat qualification, an API-calling
product peripheral ISR target test, and remaining operator LED evidence. The
generation voter does not configure or feed hardware WDG. The preserved P2 ELF
and fail-closed 86,400-second collector are ready; the run cannot share a board
with timing-sensitive USB HIL because each sample halts the CPU.

The 2026-08-10 parallel start attempt is recorded in
`docs/evidence/phase2/P2-24h-schedule-2026-08-10.md`. It did not start the
collector: the connected J-Link was S/N `20781318`, not the frozen
qualification probe `607000454`, and could not identify the target over JTAG.
The runner now enforces a per-probe exclusivity lock and records probe/target
identity when the correct hardware returns.

## Phase 3A

The five current Linux USB HIL paths are reconciled in
`docs/evidence/phase3/P3A-USB-HIL-status-2026-08-10.md`. `T-USB-006` is `PASS`
within its explicit raw-echo boundary. `T-USB-005`, `T-USB-007`, `T-USB-008`
and `T-USB-010` remain `PARTIAL` based on recorded evidence: `T-USB-007` has a
100/100 behavioral runner PASS but no recorded firmware identity. Forced-FS,
real IN/OUT endpoint HALT, manifest-bound native Windows collection, and a
single-halt post-HIL RTOS/USB snapshot now have fail-closed runners and tests.
They have not been promoted because the target USB was absent during the
2026-08-10 software verification and no current Windows evidence bundle was
available. Protocol/drop reconciliation remains P4E work.

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
native CI/functional HIL are complete. Physical cable cycling has a 100/100
behavioral run, but P3A `T-USB-007` remains `PARTIAL` until a manifest-bound
rerun; Windows native WinUSB/PnP capture remains P3A, while release
archive/package and installer provenance stay in P6. OpenOCD was
not selected and macOS is deferred by the Linux/Windows CLI scope. These
downstream items are not represented as completed evidence.

The local Linux host toolchain is also closed: Rust/Cargo 1.97.1, GCC 16
ASan/UBSan, host tests and clippy pass. The physical P3A hotplug collector has a
100/100 behavioral bundle with an explicit firmware-provenance gap. The updated
collector is fail-closed on manifest/artifact and node-access checks. The
stricter Windows PnP/provenance collector is ready,
but no current native run against the P3A root firmware is represented as
`PASS` until its evidence bundle exists.
