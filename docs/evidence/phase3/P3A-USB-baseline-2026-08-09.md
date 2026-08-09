# Phase 3A USB Vertical-Slice Baseline

Date: 2026-08-09

Status: **BASELINE PASS / PHASE 3A PARTIAL**

The root FreeRTOS firmware now owns CherryUSB through one statically allocated
USB task and one statically allocated event queue. USB interrupt priority is
fixed at 4. Endpoint callbacks enqueue with `xQueueSendFromISR`; only the owner
task starts data transfers. OUT is not rearmed until the matching IN transfer
completes, so the 2048-byte DMA buffer retains a single owner.

The production MCAN owner remains absent. MCAN0 only runs the bounded P2
internal-loopback IRQ qualification and is returned to INIT before normal USB
operation.

## Artifact

- Source commit: `e1fa77f80de5917054844f2539483172685238fb`
- Flash Debug ELF: `bc280341b4b764aa17582e378e19df8efa82e60616b9dcdf5daae358beda3f15`
- Flash Release ELF: `7db3d88a276612270a3dbfec3c00e50e2b3c6c573e7327d5559859a9215f5116`
- RAM Debug ELF: `d5c180268d5f2b8329ed626c4b7054be5be9f36b10c4a4625915770b1f53fccb`
- All three presets were built from deleted build directories. Each manifest
  records the source commit above and `source_dirty: false`.

J-Link PLUS S/N `607000454` programmed and verified 114688 bytes over JTAG at
4 MHz with VTref 3.300 V.

## USB Result

Linux enumerated `34b7:1236` at High Speed (480 Mbps). The device reports USB
2.1, one vendor interface at index 0, bulk OUT `0x01`, bulk IN `0x81`, 512-byte
HS MPS, and the Microsoft OS 2.0 BOS platform capability. The firmware also
contains the FS configuration, device qualifier, and other-speed descriptor.

Two independent host implementations completed 64 MiB pseudo-random echo:

- Python/libusb: 67,108,864 bytes, 6.468 MiB/s, zero content errors.
- Rust/rusb: 67,108,864 bytes, 11.264 MiB/s, zero content errors.
- Post-GDB resume smoke: 1,048,576 bytes, zero content errors.

The GDB USB snapshot after the two 64 MiB runs recorded:

- IRQ priority 4; initialized, online, connected, and configured all true.
- 65,536 RX and 65,536 TX completions.
- 134,217,728 RX bytes and 134,217,728 TX bytes.
- 131,073 successful queue sends; zero queue drops and zero stale events.
- Zero transfer errors; OUT armed, no IN transfer left in flight.
- USB owner stack high-water mark: 652 words.

## RTOS Result

The 15.049-second health run collected four valid samples from the same ELF.
Heartbeat and watchdog evaluation counters advanced monotonically. MCAN0
remained 1024/1024 matched with zero queue drops. Fault reason, missing voter
mask, and post-freeze allocation count were all zero. Health and MCAN task
stack watermarks were 433 and 335 words.

Detailed artifacts:

- `P3A-USB-baseline-2026-08-09.json`
- `P3A-RTOS-health-2026-08-09.json`
- `scripts/phase3/usb_owner_snapshot.gdb`

## Open Gates

This is not full Gate C closure. The current root firmware still needs the
physical FS fallback check, Windows revalidation, fragmentation/coalescing,
10 GiB plus one-hour loopback, 100 physical disconnect/reconnect cycles,
backpressure/resume, and endpoint stall/reset coverage. Malformed-message
coverage follows protocol integration.

P2 also remains `PARTIAL`: the deferred 86,400-second heartbeat qualification
must run later against the preserved P2 ELF. This Phase 3A work does not relabel
that qualification as PASS.
