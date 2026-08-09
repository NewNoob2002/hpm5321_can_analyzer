# P2 RTOS/Time/Ownership Baseline

Status: `PARTIAL`
Date: 2026-08-09
Board: `hpm5321_custom`, serial `20260723`
Probe: J-Link PLUS, S/N `607000454`, JTAG 4 MHz, VTref 3.30 V
SDK: `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e` (`validated-fork`)
Final RTOS qualification ELF SHA-256:
`c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2`

## Implemented Baseline

- FreeRTOS task, queue and software timer are statically allocated; the SDK is
  configured with its custom-heap path and dynamic allocation is disabled.
- `health_task` is the only normal runtime writer of
  PA31/PY01/PY02/PY03/PA09; the fatal hook has a terminal STATUS-on override.
- The MCHTMR reader uses high-low-high sampling and publishes a 64-bit tick.
- Assert, stack-overflow and malloc-failed hooks record a bounded GDB-visible
  fault snapshot before entering the fatal loop.
- A fixed-capacity generation voter tracks the health task and timer service.
  Debug builds expose a test-only stall mask; voter success does not feed a
  hardware watchdog yet.
- The IRQ contract enables the HPM PLIC syscall-threshold port path at priority
  4. IRQs above that numerical priority cannot call FreeRTOS APIs.
- Linker-wrapped libc allocation entry points count startup calls and reject
  evidence if any allocation occurs after the pre-scheduler freeze point.
- Flash Debug, Flash Release and RAM Debug all configure and link successfully.

## Initial Target Snapshot

The Flash Debug image was programmed and verified with J-Link. Two GDB samples
were taken two seconds apart while the scheduler continued running:

```text
boot magic=0x424f4f54 cpu=480000000 ahb=160000000 mtime=24000000
usb=160000000 can0=80000000 can2=80000000 spi2=80000000
sample1 heartbeat=24 drops=0 stack=445 led=0 tick=288317700 fault=0x00000000
sample2 heartbeat=28 drops=0 stack=445 led=0 tick=336317633 fault=0x00000000
```

This proves four 500 ms heartbeat periods, a 47,999,933-tick advance at the
24 MHz MCHTMR frequency, no health queue loss, no recorded fault and a health
stack watermark above the current 25% provisional threshold.

## Follow-up Evidence

The final Flash Debug image was programmed after the advanced contracts were
added. Controlled target tests proved:

- direct assert, stack-hook and malloc-hook injection records reasons 1, 2 and
  3 with magic `0x4641554c`, without `ebreak` trap recursion;
- timer voter stall changes `missing_mask` from `0` to `0x2`, stops the healthy
  count, and returns to `0` after the stall mask is cleared;
- two startup libc allocation calls occur before freeze, while
  `post_freeze_allocation_calls` remains zero;
- a clean 30.038-second run advances heartbeat/evaluation/healthy counts from
  45 to 104 with zero fault, queue drop, missing voter or post-freeze allocation.
- the final MCAN0 internal-loopback run submits, interrupts, queues, receives
  and matches all 1024 frames at PLIC priority 4 with zero drops, errors,
  mismatches, timeouts or post-freeze allocations; controller cleanup returns
  `CCCR.INIT=1`.

See `P2-RTOS-followup-2026-08-09.md` and
`T-RTOS-003-short-2026-08-09.json` for the earlier advanced-contract evidence.
Final artifact-bound evidence is in `T-RTOS-005-2026-08-09.json` and
`P2-final-short-health-2026-08-09.json`.

## Open Gates

The short runs do not close P2. The following remains required:

- 24-hour heartbeat with reset/assert accounting (`T-RTOS-003`);

`T-RTOS-005` now passes using the real MCAN0 interrupt, a static queue and a
static receiver task without starting the production USB or MCAN owner tasks.
STATUS target timing, polarity and the terminal solid-on fault pattern also
pass; see `T-LED-002-status-2026-08-09.json`.

Host and target evidence now cover `T-RTOS-002`, `T-RTOS-006`,
`T-RTOS-007`, and `T-RTOS-008`. Direct stack-hook injection proves the hook
path only; it is not represented as a naturally induced stack overflow.
See `T-BSP-001-uart-banner-2026-08-09.md` for the current UART-enabled artifact.
Its 447-byte physical UART capture closes `T-BSP-001` as `PASS`.
