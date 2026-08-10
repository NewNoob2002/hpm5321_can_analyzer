# Phase 3A USB HIL Status

Date: 2026-08-10

Status: **1 PASS / 4 PARTIAL**

This report is the current verdict source for the five USB HIL paths collected
on 2026-08-09. A collector process returning `PASS` means that its recorded raw
operations completed. It does not promote every referenced test ID to `PASS`.

| Test | Verdict | Recorded coverage | Remaining boundary |
|---|---:|---|---|
| `T-USB-005` | PARTIAL | 17 raw Bulk transfer sizes from 1 to 2048 bytes, including 63/64/65, 511/512/513 and owner-buffer boundaries, four exact echoes per size | Protocol-frame fragmentation and coalescing across USB transfers |
| `T-USB-006` | PASS | 24,163,749,888 verified bytes over 3,600 seconds, 11,798,706 transfers, 6.401 MiB/s, zero content errors | The verdict is raw pseudo-random echo only; it makes no protocol, CAN, FS or Windows claim |
| `T-USB-007` | PARTIAL | The runner reports behavioral PASS: 100 physical cable cycles, every re-enumerated node recorded readable/writable, exact 1 MiB echo after every cycle, maximum measured recovery 196.244 ms | The original collector recorded neither serial/build ID nor a manifest; exact firmware identity is unknown. It also makes no Windows PnP, FS, endpoint HALT, protocol or CAN claim |
| `T-USB-008` | PARTIAL | Raw 2048-byte echo recovered after host read pauses of 100, 1,000, 5,000 and 15,000 ms | Sustained protocol workload, queue/drop reconciliation and explicit overload signaling |
| `T-USB-010` | PARTIAL | Ten idle and four pending-data USB device reset/reopen cases, each followed by a 2048-byte recovery echo | A real endpoint HALT/STALL and recovery from `CLEAR_FEATURE(ENDPOINT_HALT)` |

The raw matrix evidence therefore uses `test_references`, not `test_ids`, and
contains a per-test `evidence_boundaries` verdict. `T-USB-009` remains outside
this five-path raw HIL set and follows protocol integration.

## Firmware provenance

The matrix and one-hour loopback directly recorded this host build manifest:

- Manifest: `build/hpm5321-flash-release/build-manifest.json`
- Manifest SHA-256: `41048c12cf22b8805fe8f5c17c0fe08d28662ceeb0822fa694c7735eb1de0438`
- Preset: `hpm5321-flash-release`
- Source revision: `e1fa77f80de5917054844f2539483172685238fb`
- Source dirty: `false`
- ELF SHA-256: `7db3d88a276612270a3dbfec3c00e50e2b3c6c573e7327d5559859a9215f5116`
- BIN SHA-256: `f6f8b97aed7f0173c010f506ef7e1eedd01801a270d2b50246cc8edaec3059eb`
- SDK commit: `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`
- Compiler: `riscv32-unknown-elf-gcc (gc891d8dc23e) 13.2.0`

The SDK commit is the tracked local-fork `current_build_commit`, not the
official v1.12.1 `release_commit`. The evidence remains valid for the tested
artifact but does not inherit the official-SDK clean-build identity.

The original hotplug collector did not record a manifest, serial or build ID.
The manifest-bound loopback ended 82 seconds before the hotplug run began and
both used topology `7-1.4`, but that correlation cannot prove that the device
was not replaced or reflashed. `T-USB-007` therefore has unknown firmware
identity and remains `PARTIAL` at the qualification layer even though the raw
runner status is `PASS`.

The updated collectors reject incomplete manifests and verify the recorded
ELF/BIN sizes and SHA-256 values against retained build artifacts before HIL.
They still mark `device_attested: false`, because the raw echo firmware exposes
no on-device build identifier. A provenance-complete `T-USB-007` requires a new
run with the updated collector.

## Evidence

- `T-USB-005-008-010-current.json`
- `T-USB-006-current.json`
- `T-USB-007-current.json`
- `scripts/phase3/run_usb_hil.py`
- `scripts/phase3/collect_usb_hotplug.py`

The remaining Phase 3A hardware gates are provenance-complete physical hotplug,
physical FS fallback, current Windows native WinUSB/PnP capture, real endpoint
HALT recovery, and a joint post-HIL RTOS/USB health snapshot.
