# Dual-MCAN Internal Probe Evidence

Date: 2026-07-31  
Board target: `hpm5321_custom` / HPM5321xCFx  
Probe: SEGGER J-Link S/N 607000454, JTAG 4 MHz, VTref 3.32 V

## Scope

The TCAN1044AVDRQ1 devices are not populated. This test therefore covers only
the HPM5321 controller-side resources:

- MCAN0 and MCAN2 clock initialization
- external AHB message-RAM assignment
- controller initialization in Classic CAN and CAN-FD modes
- internal loopback with standard and extended identifiers
- payload integrity for Classic 8-byte and CAN-FD 64-byte frames

It does not cover VCC/VIO rails, STB behavior, CANH/CANL, termination, bus
arbitration, error confinement, wake-up, EMC, or physical CAN-FD timing.

## Build evidence

Firmware: `tools/phase0/mcan_internal_probe`

- Build: PASS with HPM SDK 1.12.1, GNU 13.2.0, `flash_xip`
- Flash image ELF SHA-256:
  `8cb50fc7c45d6bb173943083df79943f2dd3b6fdaaad99e6ec90abc41c3cf754`
- AHB SRAM used: 5 KiB of 32 KiB
- Flash used: 64,752 bytes

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

## Deferred physical-layer closure

After both transceivers are populated:

1. Confirm the part orientation and continuity with power removed.
2. Confirm VCC is within the transceiver's required supply range and VIO
   matches the MCU I/O domain.
3. Confirm STB default and MCU control polarity before enabling transmission.
4. Measure termination resistance with power removed.
5. Power up in standby/listen-only first and verify recessive bus levels.
6. Validate Classic CAN externally on each channel before any CAN-FD claim.
7. Validate CAN-FD nominal/data timing and signal integrity on both channels.
