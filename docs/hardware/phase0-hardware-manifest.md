# Phase 0 Hardware Manifest

Status values: `PASS`, `BLOCKED`, `NOT_TESTED`, `NOT_APPLICABLE`.

## Board identity

| Item | Current evidence | Status | Required closure |
|---|---|---:|---|
| MCU | HPM5321xCFx project target | PASS | Record exact package/marking from board |
| Board | `hpm5321_custom` board package | PASS | Record PCB revision and serial number |
| SDK | Local HPM SDK 1.12.1 baseline | PASS | Preserve SDK/board-overlay checksum |
| Probe | Not inventoried | NOT_TESTED | Record J-Link/OpenOCD probe model and serial |

## USB HS contract

| Item | Current evidence | Status | Required closure |
|---|---|---:|---|
| Controller | HPM USB0 device controller | PASS | — |
| D+/D- pins | Board package maps USB0 and initializes PHY | PASS | Cross-check schematic nets |
| Endpoint capacity | `USB_SOC_DCD_MAX_ENDPOINT_COUNT=16` | PASS | Static composite validation |
| Product speed | Device enumerates at negotiated 480 Mbit/s | PASS | Repeat on Windows/macOS reference hosts |
| PHY signal path | Rework restored host enumeration; UTMI/controller evidence captured | PASS | Archive schematic/rework note |
| VBUS sensing | Runtime PHY status reported VBUS/SESSION invalid; probe temporarily uses internal override | BLOCKED | Inspect schematic and select production external/internal VBUS policy |
| Vendor interface | IF0 vendor bulk, EP1 IN/OUT, HS MPS 512; 64 MiB seeded loopback PASS | PASS | Phase 3 runs 10 GiB qualification |
| CDC ACM | Optional, two interfaces and three endpoints | PASS | Validate optional descriptor variants |
| DFU Runtime | Optional, EP0 only | PASS | Enable only after UPDATE claim passes |
| WinUSB binding | Microsoft OS 2.0 BOS descriptor verified on Linux | NOT_TESTED | Verify Windows binds only vendor interface |

### Descriptor variants

| Build | Interfaces | Data endpoints | Release use |
|---|---|---|---|
| Vendor only | IF0 vendor | EP1 OUT/IN | Minimal MVP/probe |
| Vendor + CDC | IF0 vendor, IF1/2 CDC | EP1 OUT/IN, EP2 IN, EP3 OUT/IN | Default development |
| Vendor + DFU | IF0 vendor, IF1 DFU Runtime | EP1 OUT/IN | UPDATE without CDC |
| Vendor + CDC + DFU | IF0 vendor, IF1/2 CDC, IF3 DFU Runtime | EP1 OUT/IN, EP2 IN, EP3 OUT/IN | Full optional composite |

DFU Runtime uses EP0 and only requests detach into a separately validated
bootloader. It does not write application flash while the analyzer is active.

## CAN/clock contract

| Item | Status | Required closure |
|---|---:|---|
| MCAN0 transceiver model/FD support | NOT_TESTED | Schematic/BOM inspection |
| MCAN2 transceiver model/FD support | NOT_TESTED | Schematic/BOM inspection |
| Termination and STB/EN control | NOT_TESTED | Schematic + DMM/GPIO validation |
| PLL1 source and frequency | NOT_TESTED | Runtime clock report |
| MCAN0/MCAN2 kernel clocks | NOT_TESTED | Runtime clock report + analyzer timing |

## Flash/update contract

| Item | Status | Required closure |
|---|---:|---|
| Boot medium | BLOCKED | Resolve YAML QSPI-NOR vs board-header comment |
| Linker/erase topology | NOT_TESTED | Linker map + erase experiment |
| Bootloader/rollback capacity | NOT_TESTED | Partition design and power-cut tests |

## Phase 0 USB evidence procedure

1. Build `tools/phase0/usb_hs_probe`.
2. Flash only after the normal probe/board safety preflight.
3. Capture UART banner and host USB descriptor tree.
4. Prove negotiated speed is `480M`/High-Speed; a correct HS descriptor alone
   is not sufficient.
5. Run at least vendor-only and the full composite variant on Windows, Linux
   and macOS.
6. Archive VID/PID, serial, `bNumInterfaces`, endpoint MPS, driver binding,
   disconnect/reconnect logs and firmware checksum.

## Exit rule

P0U becomes `PASS` only after real hardware proves HS enumeration, descriptor
correctness, endpoint/FIFO sufficiency, stable reconnect and platform driver
binding. The current repository can prove buildability and the static resource
budget, but it cannot prove negotiated bus speed without the board.
