# ADR Addendum — Host Stack Spike

Status: **ACCEPTED**
Date: 2026-08-03

## Decision under evaluation

The Linux/Windows CLI host core is Rust. Qt is removed from the CLI technology
gate and deferred to the GUI phase. Maintaining a second protocol/USB core is
forbidden.

## Common Linux synthetic evidence

`HOST-SPIKE-10K-v1` runs 1,000,000 deterministic records, equivalent to 100 s
at 10k frames/s. It verifies equal checksums, 99 hotplug-style reconnects and a
real process exit/checkpoint/restart recovery at frame 500,000.

| Candidate | Throughput | Binary | Checksum | Recovery |
|---|---:|---:|---:|---:|
| Rust 1.97.1 | 83,245,634 frame/s | 492,208 B | `2324f5364365f925` | PASS |
| C++17 core | 74,739,544 frame/s | 17,896 B | `2324f5364365f925` | PASS |

These microbenchmark values establish large headroom over 10k frame/s; they do
not predict USB latency or GUI performance.

## External compatibility evidence

- Cargo workspaces provide one lockfile and shared output/commands for a
  multi-package core/CLI/GUI repository:
  <https://doc.rust-lang.org/cargo/reference/workspaces.html>.
- `rusb` exposes libusb device access and hotplug, documents Windows/macOS/Linux
  support, and is MIT licensed; static vendoring still inherits libusb LGPL
  obligations: <https://docs.rs/crate/rusb/latest> and
  <https://docs.rs/rusb/latest/rusb/trait.Hotplug.html>.
- Qt supports commercial or LGPLv3/GPLv3 deployment, with module-specific
  licensing constraints that require an explicit shipping policy:
  <https://doc.qt.io/qt-6/licensing.html>.

## Current Disposition

Rust synthetic and crash-recovery lane: **PASS**.  
C++ protocol-core synthetic lane: **PASS**.  
Real Linux and Windows vendor-Bulk functional lanes: **PASS**.  
Windows native build/test/clippy CI: **PASS**.

The stack decision is locked to Rust for the Linux/Windows CLI, and the shared
protocol/session/transport core is implemented. Qt 6 is not a CLI dependency.
Physical cable cycling, Windows PnP binding archive and release packaging stay
in P3A/P6; macOS is explicitly deferred from the current scope. Qt licensing
is revisited only if the 1.0 GUI selects Qt.
