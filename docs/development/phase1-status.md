# Phase 1 Development Environment Status

Status values: `PASS`, `PARTIAL`, `BLOCKED`, `NOT_TESTED`, `NOT_APPLICABLE`.

| Gate | Status | Evidence / remaining work |
|---|---:|---|
| Git history, remote and ignore policy | PASS | Repository has tracked Phase 0 evidence and `origin`; build outputs are ignored |
| Versioned board overlay and SDK lock | PASS | `boards/hpm5321_custom` and `dependencies/hpm-sdk.lock` are tracked |
| Linux environment contract | PASS | `scripts/env/check.sh` rejects missing tools, invalid SDK paths and unlocked SDK commits |
| Flash Debug/Release and RAM Debug builds | PASS | Three CMake configure/build presets emit ELF/BIN/MAP, compilation database and build manifest |
| VSCode build/clangd contract | PASS | Tasks call only `scripts/build.sh`; clangd uses the actual Flash Debug database |
| J-Link VSCode debug profile | PARTIAL | Checked-in GDB attach profile; Phase 0 proves command-line stop/reset/read/write, but VSCode UI step evidence is pending |
| OpenOCD debug adapter | BLOCKED | Current board has no SDK OpenOCD board config; adapter decision remains open |
| Windows clean build | PARTIAL | Native executable passed HIL; clean-build tool versions, log and artifact hashes remain to archive |
| macOS clean build | NOT_APPLICABLE | Deferred by Linux/Windows CLI-first scope addendum |
| Host stack decision | PASS | Rust selected for shared core/CLI; Qt deferred to GUI and may not introduce a second protocol core |
| Rust Linux vendor-Bulk | PASS | 480M enumeration, 64 MiB exact echo, reset interruption exit code 2 and post-reset recovery passed |
| Physical cable hotplug | NOT_TESTED | Automated reset/re-enumeration passed; cable cycling evidence remains |
| Windows WinUSB and packaging | PARTIAL | Cross-built and native EXEs passed 64 MiB/reset/recovery HIL; PnP binding record, hashes and packaging remain pending |
| Protocol v1 host codec | PARTIAL | Envelope, CRC32C, semantic validation, bounded stream resync and HELLO golden vector implemented; remaining message payload codecs and firmware C parity are pending |
| Official SDK v1.12.1 clean build | BLOCKED | Current validated artifact uses fork commit `88b01b43...`; official commit remains Gate A |

The Linux host spike and physical vendor-Bulk smoke test are complete. The next
Phase 1B closure item is a native Windows CI/HIL evidence run following
`setup-windows-host.md`; macOS remains explicitly deferred.
