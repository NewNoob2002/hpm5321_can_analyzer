# Phase 1B Windows Native CI Evidence

Status: `PASS`  
Run: <https://github.com/NewNoob2002/hpm5321_can_analyzer/actions/runs/30886654542>  
Source: `e55d3c001673b1c9fa2a66a16949e36156fad5d3`  
Conclusion: `success`

## Runner And Toolchain

- Job: `build-test (windows-latest)`, database ID `91919255589`
- Microsoft Windows Server 2025 Datacenter `10.0.26100`
- Runner image `windows-2025-vs2026`, image version `20260728.188.1`
- Git `2.55.0.windows.3`
- Rust target `1.97.1-x86_64-pc-windows-msvc`
- rustc `1.97.1 (8bab26f4f 2026-07-14)`
- repository `host/Cargo.lock` SHA-256 at the tested source:
  `4c12ca3aa919f02d6496f4dcdcb3d90efbc77f02d2a63cd435e9f31326b8c7af`

## Passed Steps

```text
cargo +1.97.1 fmt --manifest-path host/Cargo.toml --all --check
cargo +1.97.1 build --manifest-path host/Cargo.toml --workspace --release --locked
cargo +1.97.1 test --manifest-path host/Cargo.toml --workspace --release --locked
cargo +1.97.1 clippy --manifest-path host/Cargo.toml --workspace --all-targets --release --locked -- -D warnings
```

All four steps passed. The Windows job compiled the protocol, host core,
usb-smoke and spike crates with the MSVC target and vendored libusb.

This report proves the Phase 1B native Windows clean source/build/test lane.
It does not replace product-release artifact hashing, PnP binding capture or
installer/package evidence; those remain P3A/P6 work.
