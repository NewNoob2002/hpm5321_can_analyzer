# Scope Addendum: SPI2 SD and Five LEDs

Stable ID: `spi2-sd-led-2026-08-09`  
Status: `APPROVED`  
Authority: user execution request after sequential Architect and Critic approval.

This addendum is normative where it is more specific than the base PRD. It
adds the board's SPI2 SD interface and five indicators without making STORAGE
part of MVP or Beta.

## Hardware Contract

In product names, `CAN1 = MCAN0` and `CAN2 = MCAN2`. CAN2 does not mean the
unused MCAN1 peripheral.

| Signal | Pin | Contract |
|---|---|---|
| SPI2 SCLK | PB11 | SD SPI clock |
| SPI2 MISO | PB12 | SD-to-MCU data |
| SPI2 MOSI | PB13 | MCU-to-SD data |
| SD CS | PB10 | GPIO CS; active-low is a BSP assumption until P0S proof |
| SD detect | PY00 | Raw card-present input; polarity, pull and debounce need P0S proof |
| CAN1 TX LED | PY01 | Product CAN1/MCAN0 successful TX completion activity |
| CAN1 RX LED | PY02 | Product CAN1/MCAN0 accepted RX activity |
| CAN2 TX LED | PY03 | Product CAN2/MCAN2 successful TX completion activity |
| CAN2 RX LED | PA09 | Product CAN2/MCAN2 accepted RX activity |
| STATUS LED | PA31 | Health/status indication |

The active-low CS constant remains a software assumption. All five LED
active-low levels and PY00 inserted-low/empty-high behavior have target/operator
confirmation. The BSP now explicitly configures a 100 kOhm PY00 internal
pull-up and Schmitt input, with a target empty-slot `NMED` result. Phase 0 must
still prove schematic drive topology, resistor, reset state, the external
detect network/debounce and target voltage/routing behavior before the
corresponding LED gates or P0S close.

## Stack Decision

Use a repository-productionized HPM SDK v1.12.1 SPI-SD protocol layer with its
bundled FatFs as the baseline. The initial media profile is target-verified SD
v2 SDHC cards marketed as 4/8/16/32 GB, FAT32, 512-byte logical sectors and
segments below the FAT32 single-file limit.

SdFat 2.3.1 can be ported with a custom HPM `SdSpiBaseClass`, but it is not a
drop-in HPM5321/FreeRTOS library. It adds a C++/Arduino-decoupling surface and
does not solve RTOS ownership, PY00 handling or product crash recovery. It is
not selected now. Reopen the dependency decision before P3C1 only when any of
these is required or measured:

- SDXC/exFAT or marketed 64/128 GB media;
- a single file larger than 4 GiB;
- failure of the native stack under the same frozen `BP-STORAGE-v1` profile.

If reopened, pin the dependency and require a non-Arduino HPM adapter, bounded
error propagation, a C ABI/C++ policy, dependency checksum/license/SBOM and the
same `T-SD-001..010` suite. Upstream references:

- <https://github.com/greiman/SdFat/releases/tag/2.3.1>
- <https://github.com/greiman/SdFat/blob/cda057318bec196183d4cc92b01bc1dd64bbfb02/src/SdCard/SdSpiCard/SpiDriver/SdSpiBaseClass.h>
- <https://github.com/greiman/SdFat/blob/cda057318bec196183d4cc92b01bc1dd64bbfb02/LICENSE.md>

## Ownership And Recovery

- `storage_task` is the sole SPI2, CS, card, filesystem and capture-file owner.
  No ISR, host-command handler or health path calls FatFs directly.
- `health_task` is the sole post-BSP LED GPIO writer. CAN owners publish
  bounded counters/event bits; ISR and timer callbacks never write LEDs.
- TX indicators publish only after successful controller completion. RX
  indicators publish only after a valid frame is accepted. Pulses may coalesce
  and are never authoritative counters.
- PY00 feeds the storage-owned debounce/hot-plug state machine. Removal
  increments `media_generation`, rejects new work, invalidates old handles and
  finishes or aborts the in-flight transfer by a bounded deadline.
- Reinsertion always reinitializes geometry, mounts, scans committed records
  and opens a new segment for the new generation.
- No-media/full/I/O errors degrade STORAGE only; CAN and USB continue under
  their existing bounded-loss policy.

## Native Stack Productionization

P3C1 must carry repository-owned fixes or versioned patches for:

1. logical sector count and erase-block geometry;
2. truthful `CTRL_SYNC` semantics tied to the product commit point;
3. finite SPI/protocol/DMA waits and task-notification/semaphore completion;
4. PY00 detect/debounce and stale-generation rejection;
5. aligned/cache-correct DMA and bounded recovery;
6. explicit `SPI_SD_SPEED_MAX_HZ=20000000` configuration;
7. fail-closed FAT32-only behavior until exFAT is explicitly claimed.

Capture durability uses preallocated segments, fixed blocks with generation,
sequence, length and CRC, a last-written commit marker, a truthful sync barrier
and redundant checkpoint metadata. A mountable filesystem alone is not proof
of committed capture integrity.

## Release DAG

Only `1.0 + STORAGE` may publish the STORAGE capability. The exact conditional
chain is `P0S -> P3C1 -> P3C2 -> P5S`:

| Node | Prerequisite | Exit evidence |
|---|---|---|
| P0S | schematic/BOM + P0H workload | electrical/media contract and frozen BP-STORAGE-v1 |
| P3C1 | P0S + P2 | SPI2/detect/generation, geometry/sync and bounded I/O |
| P3C2 | P3C1 + P3B | capture admission, commit, throughput and isolation |
| P5S | P3C2 + P4P | wire/host/golden/E2E storage contract |

MVP and Beta never claim STORAGE. Early P0S/P3C1/P3C2 work retires risk but
does not add a release dependency or capability advertisement.

## Test Contract

LED tests have one gate each:

| Test | Gate | Applicability | Purpose |
|---|---|---|---|
| T-LED-001 | B | P0 required(MVP+) | STATUS and CAN1 pin/polarity/default/routing proof |
| T-LED-002 | B | P0 required(MVP+) | health-only writer and measured STATUS patterns |
| T-LED-003 | D | P0 required(MVP+) | MCAN0 TX-complete/RX-accepted semantics |
| T-LED-004 | B | P0 required(Beta+), MVP advisory | CAN2 pin/polarity/default/routing proof |
| T-LED-005 | D | P0 required(Beta+) | MCAN2 semantics and naming proof |
| T-LED-006 | H | P0 required(MVP+) | coalescing and CAN/USB load isolation |

Storage testing strengthens `T-SD-001..010` with the pin/clock/media matrix,
multi-block throughput, geometry, truthful sync, detect/removal generation,
real power cuts, host readback and CAN/USB regression. Software reset alone is
not accepted as a power-cut result.

`docs/approved-plan/profiles/bp-storage-v1.md` is structurally versioned now,
but stays `BLOCKED` until P0S records the derived encoded rate, queue absorption
and deadlines. P3C1 requires
`python3 scripts/validate_planning_contract.py --require-storage-frozen`.
