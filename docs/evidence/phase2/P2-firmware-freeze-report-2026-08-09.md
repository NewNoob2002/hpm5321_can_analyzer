# P2 Firmware Freeze Report

- Status: `FROZEN`
- Date: 2026-08-09
- Firmware source revision: `980a38c9196dfe5971ff3b624c235edb33625e6d`
- SDK revision: `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`
- Board: `hpm5321_custom`, serial `20260723`
- Probe: J-Link PLUS, S/N `607000454`, JTAG 4 MHz

## Clean Builds

All three standard presets were built after deleting their build directories.
Every archived manifest records the firmware source revision above and
`source_dirty: false`.

| Preset | ELF SHA-256 | Result |
| --- | --- | --- |
| `hpm5321-flash-debug` | `c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2` | PASS |
| `hpm5321-flash-release` | `b16c962e9a63248eced53a21ee9b3917022fd0fa0c97b4f40151e1e5c9220306` | PASS |
| `hpm5321-ram-debug` | `0b45e14303f07a886e2e4871a6d8a2efee7853aaa135a748e641ea7d25b0c9eb` | PASS |

The complete logs and build manifests are archived beside this report. The
machine-readable index is `P2-firmware-freeze-2026-08-09.json`.

## Deployed Artifact

The final Flash Debug ELF is the endurance-test artifact. J-Link selected
`HPM5321xCFx`, probe `607000454`, JTAG 4 MHz, observed VTref 3.299 V and
reported that target Flash contents already matched the ELF before reset and
resume. See `P2-final-flash-jlink-2026-08-09.txt`.

## Preflight Results

- `T-RTOS-005`: PASS on the final ELF. MCAN0 internal loopback completed
  1024 submitted/interrupt/queue-send/received/matched frames at PLIC priority
  4 with zero queue drops, interrupt faults, terminal faults, error counters,
  mismatches, timeouts or post-freeze allocations. Cleanup returned the
  controller to `CCCR.INIT=1`.
- Final short health: PASS over 30.135 seconds and seven samples after the
  final reset. Heartbeat and voter evaluations advanced, health stack remained
  at 445 words, MCAN receiver stack remained at 335 words, and fault, queue,
  voter and allocation checks stayed clean.
- Repository validation: 76 Python contract/integration tests PASS;
  `git diff --check` PASS before the firmware source commit.
- P2 boundary: no production USB or MCAN owner task starts, and the MCAN test
  does not connect the external CAN pads.

## Freeze Rule

Only endurance evidence and closure documents may change after this point.
Any firmware source, build configuration, SDK or toolchain change invalidates
this freeze and requires a new three-preset clean build, flash, short
qualification and 86,400-second run.

The only remaining P2 runtime gate is the full 86,400-second `T-RTOS-003`
heartbeat qualification. CAN2 activity semantics remain a Beta gate and are
outside this P2 freeze.
