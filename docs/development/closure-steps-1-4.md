# Closure Runbook: P0S, USB Hotplug, Windows Evidence, Local Toolchain

Date: 2026-08-09

## Current checkpoint

| Step | Status | Close condition |
|---|---:|---|
| 1. P0S / `BP-STORAGE-v1` | BLOCKED | Frozen `BP-CAN-BETA-v1`, schematic/BOM electrical proof, distinct PY00 inserted/removed levels, and two-vendor 4/8/16/32 GB SDHC matrix |
| 2. P3A / `T-USB-007` | NOT_TESTED | 100 physical cable disconnect/reconnect cycles with successful recovery transfer after every cycle |
| 3. Windows PnP/provenance | PARTIAL | Current native collector bundle proves interface-0 WinUSB binding, hashes, 64 MiB echo and disconnect recovery; P6 separately requires the actual product package install lifecycle |
| 4. Local Cargo/sanitizers | PASS | Rust/Cargo, fmt, 55 release tests, clippy, GCC sanitizer probe and four C parity/session tests all pass |

## 1. P0S

Populate a copy of
`docs/evidence/phase0/P0S-storage-evidence.template.json` only from measured
evidence. The validator requires the full media matrix and rejects placeholder
or one-state detect data.

```sh
python3 scripts/phase0/storage_profile.py calculate \
  --encoded-rate <frozen-encoded-bytes-per-second>
python3 scripts/phase0/storage_profile.py validate \
  --evidence docs/evidence/phase0/P0S-storage-evidence.json
python3 scripts/validate_planning_contract.py --require-storage-frozen
```

The current two J-Link samples both read `0xF00D00E0 = 0x0000000E`
(`PY00=0`). Because no confirmed state transition was captured, these samples
do not prove detect polarity.

## 2. Linux physical hotplug

Build the exact recovery executable, then run the observer. It writes evidence
after each completed cycle, so an interruption preserves progress without
claiming PASS.

```sh
cargo +1.97.1 build --manifest-path host/Cargo.toml \
  --release --locked -p hpm-usb-smoke
python3 scripts/phase3/collect_usb_hotplug.py --cycles 100
```

Only physically unplugging/reconnecting the device cable qualifies. A J-Link
reset, USB software reset or unproven hub-control operation does not.
The archived 2026-08-09 permission preflight reached topology `7-1.4` but
failed before cycle 1 because the USB device node was `root:root 0660`; install
the udev rule from `setup-linux.md` and reconnect before retrying.

## 3. Windows native evidence

From an x86-64 Windows PowerShell checkout with the target connected:

```powershell
.\scripts\phase1\collect_windows_phase1b.ps1 -ExerciseDisconnectRecovery
```

The command fails closed unless the target vendor interface is bound to
`WinUSB`, the native build/tests pass, exact hashes exist, 64 MiB echo passes,
the long transfer fails on a physical disconnect and a post-enumeration echo
recovers. Preserve both the generated ZIP and `.sha256` file. The ZIP is an
evidence archive, not a substitute for the later P6 product installer.

## 4. Local toolchain

Closed by `docs/evidence/phase1/T-HOST-LOCAL-TOOLCHAIN-report.md`. Re-run the
listed commands after compiler or Rust upgrades.
