# Host Third-Party License Inventory

Generated from `host/Cargo.lock` / Cargo package metadata for the Phase 1B
Rust USB smoke backend. Exact license texts must be included by the release
packaging lane.

| Package | Version | Declared license |
|---|---:|---|
| rusb | 0.9.4 | MIT |
| libusb1-sys | 0.7.0 | MIT |
| libc | 0.2.189 | MIT OR Apache-2.0 |
| cc | 1.4.0 | MIT OR Apache-2.0 |
| find-msvc-tools | 0.1.9 | MIT OR Apache-2.0 |
| pkg-config | 0.3.33 | MIT OR Apache-2.0 |
| shlex | 2.0.1 | MIT OR Apache-2.0 |
| vcpkg | 0.2.15 | MIT OR Apache-2.0 |

`rusb` is built with its `vendored` feature. The resulting native libusb is
LGPL-2.1-or-later; distributing a statically linked CLI therefore requires the
libusb LGPL compliance bundle and relinking materials. This must be resolved
before Windows/Linux release packaging even though the Rust wrapper is MIT.
