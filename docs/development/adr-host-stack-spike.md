# ADR Addendum — Host Stack Spike

Status: **PARTIAL / decision not yet locked**  
Date: 2026-08-03

## Decision under evaluation

Select one v1 host core: Rust, or C++ with Qt 6. Maintaining both is forbidden.
The approved default remains Rust until the complete evidence gate changes it.

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

## Current disposition

Rust synthetic and crash-recovery lane: **PASS**.  
C++ protocol-core synthetic lane: **PASS**.  
Qt 6 compile/deployment lane: **BLOCKED** because Qt 6 is not installed on the
current Linux reference host. Native libusb development metadata is also
absent, so neither candidate has completed real USB hotplug testing.
Windows and macOS packaging remain NOT_TESTED.

No final stack lock is issued yet. The next gate installs/provisions Qt 6 and
libusb development inputs in a controlled environment, adds equivalent fake
USB interfaces to both candidates, then executes real device hotplug and
Windows/macOS packaging checks. Formal host codec work remains prohibited.
