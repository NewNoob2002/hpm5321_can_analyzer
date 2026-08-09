# P2 RTOS Follow-up Evidence

Status: `PARTIAL`
Date: 2026-08-09
Board: `hpm5321_custom`, serial `20260723`
Probe: J-Link PLUS, S/N `607000454`, JTAG 4 MHz, VTref 3.30 V
SDK: `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e` (`validated-fork`)

## RTOS Qualification Artifact

Flash Debug ELF SHA-256:
`08364c0d6fca038dcafe5ef0fdb7f8bfb63d6667c04a7c47fadc0f6e1f155f8a`

This ELF contains `USE_SYSCALL_INTERRUPT_PRIORITY=1`, the HPM threshold-aware
port symbols, static FreeRTOS object creation, allocation wrappers, and no
`pvPortMalloc` or `vPortFree` symbol. Its target results remain artifact-bound
to this hash.

The board now runs the UART-enabled Flash Debug image
`faddfc9174fc3c1b9d4395a40c97bb1a89a66e20ab3378d098b93edb30494a90`.
That image received a target health spot check; it does not relabel the earlier
fault-injection or 30-second soak results.

## T-RTOS-002 Direct Hook Injection

The CMake cache variable `APP_FAULT_INJECT_REASON=1..3` directly invokes each
hook after startup and allocation freeze. These tests prove the hook recording
paths; the stack case is not a naturally induced overflow.

| Reason | ELF SHA-256 | GDB result |
|---:|---|---|
| 1 assert | `5472c799818f2a9a39a4d25f62c49a6208af4f0fb0aa654ed86a2e98b361ea25` | `magic=0x4641554c line=64 hash=0xa98aeb7c tick=318453 frozen=1 post=0` |
| 2 stack hook | `bc402210fb3745095b6cc2d669b9b3b726f8249b52da740ad011aea2c6b9e2c6` | `magic=0x4641554c line=0 hash=0xaf05dfa3 tick=318380 frozen=1 post=0` |
| 3 malloc hook | `e2ea13bc189458cb2dd629410726821b095dc40d10e88c263bcafe7764953bc1` | `magic=0x4641554c line=0 hash=0x811c9dc5 tick=318019 frozen=1 post=0` |

The fatal loop contains no `ebreak`, so each image remained in `app_fatal`
without recursively entering the trap handler.

## T-RTOS-006 Allocation Freeze

GNU linker `--wrap` instrumentation covers `malloc/calloc/realloc/free` and
their reentrant newlib entry points. The application freezes the counter after
logger, clock, static task, static queue and static timer setup, before the
scheduler starts.

The clean target run reports `allocations=2`, `alloc_frozen=1`, and
`post_freeze_allocations=0` in all seven samples. This distinguishes the two
startup libc allocations from the required no-allocation runtime interval.
FreeRTOS dynamic allocation remains compile-time disabled.

## T-RTOS-007 Stable 64-bit Time

`app_time_read_stable()` is a host-testable pure C core. Tests cover:

- stable high-low-high sampling;
- a forced low-word rollover where the high word changes once;
- two consecutive torn reads before a stable sample.

The production wrapper reads the two words at `HPM_MCHTMR_BASE`. The clean
target run holds one boot timestamp and advances the 24 MHz timebase from
`540318858` to `1248318860`.

## T-RTOS-008 Generation Voters

The required mask contains health task bit 0 and timer service bit 1. On the
final default artifact, GDB-controlled debug injection produced:

```text
BASE eval=162 healthy=162 missing=0x00000000 gen_health=162 gen_timer=162 post=0
STALL eval=167 healthy=162 missing=0x00000002 gen_health=167 gen_timer=162 post=0
RECOVER eval=171 healthy=166 missing=0x00000000 gen_health=171 gen_timer=166 post=0 fault=0x00000000
```

The health task uses a finite receive timeout, so it evaluates even when the
timer service voter is absent. This voter currently determines feed
eligibility only; no hardware watchdog is configured or fed.

## IRQ Contract

The build defines `USE_SYSCALL_INTERRUPT_PRIORITY=1` and fixes
`configMAX_SYSCALL_INTERRUPT_PRIORITY=4`. HPM's PLIC port masks numerical
priorities at or below 4 during kernel critical sections; priorities above 4
remain active and cannot call FreeRTOS APIs. The application header provides a
compile-time assertion for every future API-calling ISR.

This freezes the contract but does not close the target half of `T-RTOS-005`:
there is no product USB, MCAN or storage peripheral ISR yet to exercise with an
ISR-safe API.

## T-BSP-001 UART Boot Banner

The root firmware now enables the board UART0 console on PA00/PA01 at 921600
baud. A machine-readable `P2_BOOT` line reports firmware semantic version,
SDK release and build, board name and PCB revision, UART settings, raw PPOR
reset flags and a decoded reset cause. EasyLogger retains the RTT core without
linking RTT libc syscalls, so UART remains the sole stdout owner.

All three presets build. The UART-enabled Flash Debug image was programmed and
verified, then reported UART0 as configured and continued with heartbeat 36,
watchdog healthy 36/36, 447-word stack watermark, and zero post-freeze
allocations. A QinHeng `1a86:55d3` adapter (serial `586D017868`) then captured
the complete 447-byte UART boot output at 921600 8N1 after a J-Link reset. The
exact `P2_BOOT` line matched the firmware, SDK/build, board/revision, UART and
debug-reset contract, so `T-BSP-001` is `PASS`. See
`T-BSP-001-uart-banner-2026-08-09.md` for the complete raw text.

## Short Soak

`T-RTOS-003-short-2026-08-09.json` contains seven GDB samples over 30.038
seconds. Boot timestamp/reset snapshot stay constant; heartbeat, evaluation and
healthy counts advance together from 45 to 104; stack watermark is 447 words;
fault, queue drop, missing voter and post-freeze allocation remain zero.

The collector marks this run `qualification_status: PARTIAL`. Only an actual
86,400-second run can close `T-RTOS-003`.
