# Phase 1 Development Environment Status

Status values: `PASS`, `PARTIAL`, `BLOCKED`, `NOT_TESTED`.

| Gate | Status | Evidence / remaining work |
|---|---:|---|
| Git history, remote and ignore policy | PASS | Repository has tracked Phase 0 evidence and `origin`; build outputs are ignored |
| Versioned board overlay and SDK lock | PASS | `boards/hpm5321_custom` and `dependencies/hpm-sdk.lock` are tracked |
| Linux environment contract | PASS | `scripts/env/check.sh` rejects missing tools, invalid SDK paths and unlocked SDK commits |
| Flash Debug/Release and RAM Debug builds | PASS | Three CMake configure/build presets emit ELF/BIN/MAP, compilation database and build manifest |
| VSCode build/clangd contract | PASS | Tasks call only `scripts/build.sh`; clangd uses the actual Flash Debug database |
| J-Link VSCode debug profile | PARTIAL | Checked-in GDB attach profile; Phase 0 proves command-line stop/reset/read/write, but VSCode UI step evidence is pending |
| OpenOCD debug adapter | BLOCKED | Current board has no SDK OpenOCD board config; adapter decision remains open |
| Windows clean build | NOT_TESTED | Requires Windows reference host |
| macOS clean build | NOT_TESTED | Requires macOS reference host |
| Rust versus C++/Qt host stack spike | PARTIAL | Rust and C++ core pass the common 10k/crash profile; Qt 6, real USB and Windows/macOS packaging remain blocked/not tested |
| Official SDK v1.12.1 clean build | BLOCKED | Current validated artifact uses fork commit `88b01b43...`; official commit remains Gate A |

Phase 1A closes only the Linux build/configuration lane. The next independent
slice is the host-stack spike; Windows/macOS and debug-adapter UI evidence can
proceed without blocking its synthetic backend work.
