# Closure Runbook: P0S, USB Hotplug, Windows Evidence, Local Toolchain

Date: 2026-08-09

## Current checkpoint

| Step | Status | Close condition |
|---|---:|---|
| 1. P0S / `BP-STORAGE-v1` | BLOCKED | PY00 polarity/internal pull and one aigo 16 GB read-only SDHC/FAT32 run are PASS; still needs frozen `BP-CAN-BETA-v1`, schematic/BOM CS/external-detect proof, measured debounce, a second 16 GB vendor and two vendors at each of 4/8/32 GB |
| 2. P3A / `T-USB-007` | PARTIAL | 100/100 physical cable cycles, recorded readable/writable udev nodes and exact 1 MiB recovery echo after every cycle; the original collector did not bind a manifest/serial/build ID, so a provenance-complete rerun is required |
| 3. Windows PnP/provenance | PARTIAL | Functional WinUSB HIL proves 64 MiB echo and disconnect recovery; a current native PnP binding record and native EXE hash archive remain P3A, while the product installer lifecycle remains P6 |
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

J-Link `mem32 0xF00D00E0,1` read `0x0000000E`/PY00=0 with the card inserted and
`0x0000000F`/PY00=1 with the operator-confirmed empty slot. Detect polarity is
therefore PASS and active-low. The explicit 100 kOhm internal pull-up produced
the correct empty-slot level. A read-only run on an operator-identified aigo
16 GB card passed SD v2 SDHC initialization, CID/CSD/geometry, sector-0 and
FAT32 mount at a 20 MHz ceiling; the remaining media matrix, schematic/BOM
external network and measured contact-debounce evidence remain open.

## 2. Linux physical hotplug

Build the exact recovery executable, then run the observer. It writes evidence
after each completed cycle, so an interruption preserves progress without
claiming PASS.

```sh
cargo +1.97.1 build --manifest-path host/Cargo.toml \
  --release --locked -p hpm-usb-smoke
python3 scripts/phase3/collect_usb_hotplug.py --cycles 100
```

The collector allows up to 15 seconds after each sysfs re-enumeration for xHCI
port recovery, udev and libusb to become ready. Every smoke attempt and the
measured recovery time remain in the evidence; exhausting the window fails the
run. Wait for the printed PASS before the next unplug and keep each physical
disconnect stable for about one second to avoid counting connector bounce.

Only physically unplugging/reconnecting the device cable qualifies. A J-Link
reset, USB software reset or unproven hub-control operation does not.
The archived permission preflight failed at cycle 0. After installing the udev
rule and reconnecting, `/dev/bus/usb/007/111` became `root:dialout 0660` and a
1 MiB exact echo passed before the formal 100-cycle rerun.

The current formal rerun completed 100/100 cycles with continuous cycle
numbering, all device nodes recorded readable/writable and every 1 MiB exact
echo successful. Maximum measured recovery was 196.244 ms. The executable SHA-256 was
`e11427c2804ebe1442c2973469d875b0c2242289d71d0cc56bf7ff748a2c8c47`;
the machine-readable record is
`docs/evidence/phase3/T-USB-007-current.json`.

The hotplug verdict and the other four current USB HIL paths are reconciled in
`docs/evidence/phase3/P3A-USB-HIL-status-2026-08-10.md`. In particular, the
original hotplug collector did not record firmware identity, and the
device-reset cases are only partial evidence for `T-USB-010`; endpoint HALT is
not yet proven.

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
