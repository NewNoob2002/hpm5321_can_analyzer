# Windows Host Setup (Phase 1B)

## Scope

Phase 1B supports the Rust CLI on 64-bit Windows and Linux. macOS and Qt are
outside this phase. The target USB interface is vendor-specific interface 0,
using bulk OUT endpoint `0x01` and bulk IN endpoint `0x81`.

## Toolchain

- Windows 10 or later, x86-64
- Rust `1.97.1` with the MSVC target
- Visual Studio Build Tools with the C++ workload
- The repository's locked `host/Cargo.lock`

The `rusb` dependency enables its vendored libusb build. Windows therefore uses
libusb's WinUSB backend without requiring a separate libusb development package.
The device must bind interface 0 to Microsoft's WinUSB driver. Do not replace
the driver for unrelated composite interfaces when CDC or DFU are later enabled.

## Build and host-only verification

Run from PowerShell at the repository root:

```powershell
rustup toolchain install 1.97.1 --profile minimal --component clippy,rustfmt
cargo +1.97.1 fmt --manifest-path host/Cargo.toml --all --check
cargo +1.97.1 build --manifest-path host/Cargo.toml --workspace --release --locked
cargo +1.97.1 test --manifest-path host/Cargo.toml --workspace --release --locked
cargo +1.97.1 clippy --manifest-path host/Cargo.toml --workspace --all-targets --release --locked -- -D warnings
```

## Hardware smoke test

With the Phase 1 USB echo firmware running:

```powershell
.\host\target\release\hpm-usb-smoke.exe --bytes 67108864
```

Expected result: one `PASS platform=windows ... bytes=67108864` line and process
exit code `0`.

Stable smoke-tool exit codes:

| Code | Meaning |
|---:|---|
| 0 | Exact requested transfer completed |
| 2 | Device, permission, USB transfer, or data-integrity failure |
| 64 | Invalid command-line usage |

## Evidence Boundaries

Phase 1B requires the pinned native Windows build/test/clippy lane plus a real
functional open/transfer/reset/recovery result. Those are archived in
`T-HOST-WINDOWS-CI-report.md` and `T-HOST-USB-WINDOWS-report.md`.

P3A/P6 product qualification additionally archives all of the following under
`docs/evidence/phase1/` (the collector script writes a fresh bundle):

Archive all of the following under `docs/evidence/phase1/`:

1. Windows edition/build and Rust/Visual Studio tool versions.
2. `Get-PnpDevice` output identifying `VID_34B7&PID_1236` and WinUSB binding for interface 0.
3. The exact clean-build commands and logs.
4. SHA-256 of `hpm-usb-smoke.exe` and `host/Cargo.lock`.
5. A 64 MiB exact echo PASS log.
6. One disconnect/reset during a long transfer, a non-zero exit, re-enumeration,
   and a subsequent successful transfer.

Run `scripts/phase1/collect_windows_phase1b.ps1` from PowerShell to collect the
current environment, PnP record, clean build/tests, hashes and a 64 MiB HIL
result. CI proves native source/build correctness; it does not replace PnP,
physical USB or release-artifact provenance.
