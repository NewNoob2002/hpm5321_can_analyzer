# Phase 0 Hardware Manifest

Status values: `PASS`, `PARTIAL`, `BLOCKED`, `NOT_TESTED`, `NOT_APPLICABLE`.

## Board identity

| Item | Current evidence | Status | Required closure |
|---|---|---:|---|
| MCU | Build/debug target is HPM5321xCFx; physical marking not archived | NOT_TESTED | Record package marking/photo |
| Board | `hpm5321_custom`; PCB revision `Gerber_PCB1_2026-07-23`; serial `20260723` | PASS | Add marking/photo to the release evidence archive |
| SDK | Official v1.12.1 commit `12bd9249...` completed all three clean presets; historical hardware probes remain tied to their recorded fork revisions | PASS | Preserve `docs/evidence/phase1/T-DEV-001-003-official-sdk-clean-build-report.md`; hardware evidence remains artifact-specific |
| Board overlay integrity | All 9 members pass `sha256sum -c`; `SHA256SUMS` digest `84e8b800aaef899fb26c7be919ea57b1d35725742df7a9051f822821d2c66006` | PASS | Recompute whenever reviewed overlay sources change |
| Probe | SEGGER J-Link, S/N 607000454; JTAG 4 MHz; VTref 3.32 V | PASS | Preserve probe/tool version in test evidence |

## SPI2 SD and indicator contract

Planning addendum: `spi2-sd-led-2026-08-09`. Product aliases are
`CAN1 = MCAN0` and `CAN2 = MCAN2`; CAN2 does not map to MCAN1.

| Signal | Pin | Current evidence |
|---|---|---|
| SPI2 SCLK | PB11 | Board pinmux selects SPI2 SCLK with loopback |
| SPI2 MISO | PB12 | Board pinmux selects SPI2 MISO |
| SPI2 MOSI | PB13 | Board pinmux selects SPI2 MOSI |
| SD CS | PB10 | Board pinmux/header select GPIO CS; active-low is not yet electrically proven |
| SD detect | PY00 | Board pinmux/header select GPIO input; inserted=0 and empty=1 observed; explicit 100 kOhm internal pull-up and Schmitt input configured |
| CAN1 TX LED | PY01 | Board pinmux/header select GPIO; active-low confirmed |
| CAN1 RX LED | PY02 | Board pinmux/header select GPIO; active-low confirmed |
| CAN2 TX LED | PY03 | Board pinmux/header select GPIO; active-low confirmed |
| CAN2 RX LED | PA09 | Board pinmux/header select GPIO; active-low confirmed |
| STATUS LED | PA31 | Existing board GPIO; active-low confirmed |

| Contract item | Status | Required closure |
|---|---:|---|
| Source pin mapping | PASS | `scripts/validate_planning_contract.py` remains green |
| Five LED active levels | PASS | Operator confirmed STATUS/CAN1 TX/RX/CAN2 TX/RX all illuminate at GPIO level 0; raw record is `T-LED-polarity-2026-08-09.json` |
| LED drive, resistor, reset/default state and one-by-one routing | NOT_TESTED | Schematic review plus target voltage/routing evidence |
| SD CS polarity, drive and reset/default state | NOT_TESTED | Schematic review plus target voltage/routing evidence |
| PY00 present/absent level and polarity | PASS | J-Link `mem32 0xF00D00E0,1`: inserted `0x0000000E`/PY00=0; operator-confirmed empty slot `0x0000000F`/PY00=1; raw record `P0S-PY00-detect-2026-08-09.json` |
| PY00 internal pull-up and empty-slot behavior | PASS | IOC/PIOC `PAD_CTL=0x01060000`; target read PY00=1 and the read-only probe returned `NMED` without SPI initialization; `P0S-SPI-SD-probe-2026-08-09.json` |
| PY00 external network and debounce | NOT_TESTED | Add schematic/BOM external-network proof and measured insertion/removal bounce trace |
| SD v2 SDHC 4/8/16/32 GB FAT32 matrix | PARTIAL | aigo 16 GB passed read-only init, CID/CSD/geometry, sector-0 and FAT32 mount at a 20 MHz ceiling; still needs a second 16 GB vendor and two vendors at each of 4/8/32 GB; `P0S-SPI-SD-probe-2026-08-09.json` |
| `BP-STORAGE-v1` derived rate/deadline freeze | BLOCKED | Freeze `BP-CAN-BETA-v1`, calculate/validate with `scripts/phase0/storage_profile.py`, then run the frozen-mode planning validator |

The source-reviewed table is not electrical proof. Only `1.0 + STORAGE` may
claim STORAGE, through `P0S -> P3C1 -> P3C2 -> P5S`; MVP/Beta remain
independent of this conditional branch.

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
| CDC ACM | Static resource model only; no CDC descriptor/firmware implementation | NOT_TESTED | Implement, build and enumerate the CDC variant |
| DFU Runtime | Static resource model only; no DFU Runtime descriptor/firmware implementation | NOT_TESTED | Implement only when UPDATE scope is enabled, then enumerate it |
| WinUSB binding | Microsoft OS 2.0 BOS descriptor verified on Linux | NOT_TESTED | Verify Windows binds only vendor interface |

### Planned descriptor variants (resource model, not implementation evidence)

| Build | Interfaces | Data endpoints | Release use |
|---|---|---|---|
| Vendor only | IF0 vendor | EP1 OUT/IN | Minimal MVP/probe |
| Vendor + CDC | IF0 vendor, IF1/2 CDC | EP1 OUT/IN, EP2 IN, EP3 OUT/IN | Default development |
| Vendor + DFU | IF0 vendor, IF1 DFU Runtime | EP1 OUT/IN | UPDATE without CDC |
| Vendor + CDC + DFU | IF0 vendor, IF1/2 CDC, IF3 DFU Runtime | EP1 OUT/IN, EP2 IN, EP3 OUT/IN | Full optional composite |

DFU Runtime uses EP0 and only requests detach into a separately validated
bootloader. It does not write application flash while the analyzer is active.

## CAN/clock contract

| Item | Current evidence | Status | Required closure |
|---|---|---:|---|
| MCAN0 transceiver | TCAN1044AVDRQ1 populated; TXD/RXD digital isolation or level conversion confirmed | PASS | External listen-only and controlled transmit validation |
| MCAN2 transceiver | TCAN1044AVDRQ1 specified, not populated; deferred from current single-channel scope | BLOCKED | Populate and test in Beta dual-channel phase |
| MCAN0 isolated supply | VCC=5.2 V, VIO=5.2 V | PASS | Record instrument and powered test conditions for formal Gate evidence |
| STB default | 10 kOhm pull-down to `ISO_GND`; powered STB=0.1 V | PASS | Record instrument/raw log for formal Gate evidence |
| MCAN power-up containment | `board_init()` first disconnects MCAN pads; controller mode is configured before application reconnects pinmux | BLOCKED | Warm-reset software containment implemented; unconditional reset-to-first-instruction safety requires future STB default-high/control hardware |
| MCAN0 termination | Power-off CANH-to-CANL measurement: switch on=119 ohm; switch off=`OL/0L` (open circuit) | PASS | — |
| MCAN0 bus idle | CANH=2.52 V and CANL=2.52 V with no external node; continuity verified | PASS | Confirm again with the CAN debugger attached before traffic |
| PLL1/MCAN source | Custom board initializes MCAN0 and MCAN2 from PLL1 clock 0, divider 10 | PASS | — |
| MCAN0 kernel clock | Runtime probe reports 80,000,000 Hz | PASS | Reconfirm against measured bus timing after transceiver population |
| MCAN2 kernel clock | Runtime probe reports 80,000,000 Hz | PASS | Reconfirm against measured bus timing after transceiver population |
| MCAN0 internal loopback | Classic + FD, standard + extended ID, 8/64-byte payload: 4/4 PASS | PASS | External listen-only and active bus tests remain required |
| MCAN2 internal loopback | Classic + FD, standard + extended ID, 8/64-byte payload: 4/4 PASS | PASS | External listen-only and active bus tests remain required |
| MCAN0 listen-only initialization | 500 kbit/s, 3 s; initialization PASS, TEC/REC/CEL=0, no warning/passive/bus-off; RX count was zero | PASS | Proves passive safe state only, not external receive |
| MCAN0 external receive | Normal-mode, software-zero-TX proof received and matched one standard Classic frame: ID `0x321`, DLC 8, data `48 50 4D 52 00 00 00 01`; TEC/REC=0, no warning/passive/bus-off | PASS | Hardware ACK was required because the board was the only receiving node; standalone listen-only produced sender ACKError and could not complete a frame |
| MCAN0 controlled transmit, historical image | Target 100/100 success and external `CANDBG-01/CAN0` capture 100/100; ID `0x123`, DLC 8, sequence 0..99; TEC/REC/CEL=0 | PASS | Valid hardware engineering evidence, but source revision predates safe-order patch and was not versioned |
| MCAN0 controlled transmit, reset-disarmed image | ABI-v4 results are independent/unbound; ABI-v5 nonce `0xA504` target TX 100/100, external reception/timing, flash ELF match and cleanup PASS | PARTIAL | T-CAN-012 remains partial due reset-to-first-instruction/external zero-traffic gaps; formal product T-CAN-013 remains NOT_TESTED |

Current physical-bus bring-up scope is MCAN0 only. MCAN2 controller-side
evidence is retained, but MCAN2 transceiver and external-bus closure are
deferred to the Beta dual-channel phase.

The TXD/RXD digital isolation or level-conversion boundary was confirmed before
active testing. This resolves the earlier 5 V VIO-to-MCU safety concern.

The internal CAN-FD cases prove controller and message-RAM capability only.
They do not establish the product's physical-layer CAN-FD capability; that
claim remains capability-controlled until the populated transceivers and PCB
signal path pass external-bus validation.

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

The Linux Phase 0 minimum USB probe has real 480 Mbit/s enumeration, vendor
descriptor, Bulk integrity and software-reset evidence. The broader product
P0U Gate remains open for production VBUS policy, Windows/macOS binding and
the Phase 3 physical reconnect/10 GiB qualification.
