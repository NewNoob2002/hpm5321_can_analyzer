# Dual-MCAN Internal Probe Evidence

Date: 2026-07-31  
Board target: `hpm5321_custom` / HPM5321xCFx  
Probe: SEGGER J-Link S/N 607000454, JTAG 4 MHz, VTref 3.32 V

## Scope

MCAN0's TCAN1044AVDRQ1 is populated and hardware-enabled; MCAN2's transceiver
is not populated. This test nevertheless covers only controller-side resources
because the probe never connects either controller to its physical pads:

- MCAN0 and MCAN2 clock initialization
- external AHB message-RAM assignment
- controller initialization in Classic CAN and CAN-FD modes
- internal loopback with standard and extended identifiers
- payload integrity for Classic 8-byte and CAN-FD 64-byte frames

It does not cover VCC/VIO rails, STB behavior, CANH/CANL, termination, bus
arbitration, error confinement, wake-up, EMC, or physical CAN-FD timing.

## Build evidence

Firmware: `tools/phase0/mcan_internal_probe`

- Build: PASS with HPM SDK 1.12.1 local-fork commit
  `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`, GNU 13.2.0, `flash_xip`
- Flash image ELF SHA-256:
  `cd5585e76cc8f722af63afbffbc5fc790ed96658f593ef94550e74fd880011c7`
- AHB SRAM used: 5 KiB of 32 KiB
- Flash used: 64,736 bytes

Source manifest: `T-CAN-INTERNAL-source-manifest.sha256`, SHA-256
`747fb85e13191bacd7a53fc92b6b6f1628ef414b0c0e140af0b9810e51fc738b`.
Raw GDB/compare-sections evidence:
`docs/evidence/phase0/T-CAN-001-002-internal-safe-gdb.txt`.

## Target result

GDB downloaded the ELF, and `compare-sections` matched every programmed
section. At the terminal breakpoint, `g_mcan_probe_result` contained:

| Field | MCAN0 | MCAN2 |
|---|---:|---:|
| Base | `0xF0280000` | `0xF0288000` |
| Source clock | 80,000,000 Hz | 80,000,000 Hz |
| Message RAM status | success | success |
| Classic init status | success | success |
| CAN-FD init status | success | success |
| Passed flags | `0xF` | `0xF` |
| Failed flags | `0x0` | `0x0` |
| Frames passed | 4 | 4 |
| Frames failed | 0 | 0 |

Aggregate result:

- magic: `0x50415353` (`PASS`)
- channels tested: 2
- channels passed: 2
- total cases: 8/8 PASS
- PB00/PB01/PB08/PB09 `FUNC_CTL=0`: GPIO-safe mux remained selected; internal
  loopback did not connect either MCAN controller to the physical transceivers

## Hardware facts recorded after the probe

- TXD/RXD digital isolation or level conversion was confirmed before active
  physical-bus testing.
- VCC and VIO measure 5.2 V from isolated `ISO_5V`, derived from `SYS_5V`.
- STB has a 10 kOhm pull-down to `ISO_GND` and measures 0.1 V, requesting
  normal mode.
- The switch-controlled termination measures 119 ohm.
- CANH and CANL continuity has been verified.
- With no external node, CANH and CANL both measure 2.52 V.
- Current external-bus bring-up is intentionally limited to MCAN0; MCAN2 is
  deferred until the Beta dual-channel phase.

## Deferred MCAN0 physical-layer closure

Before active MCAN0 transmission:

1. Recheck the attached debugger's termination and 500 kbit/s configuration.
2. Start MCAN0 in listen-only mode and inspect receive/error state.
3. Transmit only the approved Classic CAN diagnostic frame after listen-only.
4. Reconcile target counters with the debugger capture.
5. Defer MCAN0 CAN-FD physical timing and all MCAN2 external tests.
