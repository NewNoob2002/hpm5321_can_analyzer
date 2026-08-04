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
| Protocol v1 host codec | PASS | Envelope, negotiation, config/capture/diagnostic/session, filters, TX arm/disarm, CAN_TX/cancel, CAN RX batch and events implemented with 36 golden vectors; the pure-C99 `protocol/v1/c` codec is byte-parity proven and runs the same vectors under ASan/UBSan. What remains is not parity but wiring the codec into the firmware USB stack (lands with P3A/P4E) |
| Protocol v1 C codec parity | PASS | Pure-C99 codec under `protocol/v1/c` decodes and re-encodes all 36 golden vectors byte-exact (host harness + ASan/UBSan + RISC-V cross compile); wiring into the firmware USB stack lands with P3A/P4E |
| Protocol v1 device session core | PASS | Pure-C99 session engine under `protocol/v1/c` implements CAS generations, arm epoch, conservative TX admission (token buckets + reserved load), exactly-once TX result ledger with post-guard slot reclaim, replay cache with retention preflight, bounded-loss accounting and priority egress queues. Enforces HELLO-first/version negotiation, stamps `device_event_sequence` into every async event frame, disarms TX on config change and rejects oversize dequeues instead of truncating. Host scenario + vector harnesses (incl. ASan/UBSan) pass |
| Host transport + fake backend | PASS | `host/crates/core` (hpm-usb-can-core) defines the frame-oriented `Transport` trait with `FakeTransport`/`FakeDevice` (in-memory v1.0 device: HELLO-first negotiation, CAS, arm epoch, TX ledger reclaim, replay cache, capture streaming, loss injection, hotplug reset) and a rusb `UsbTransport` (FIFO frame order); fake-backend parity flows pass, clippy clean |
| Official SDK v1.12.1 clean build | PASS | Official commit `12bd9249...` clean rebuild evidence: `docs/evidence/phase1/T-DEV-001-003-official-sdk-clean-build-report.md` |

The Linux host spike and physical vendor-Bulk smoke test are complete. The next
Phase 1B closure item is a native Windows CI/HIL evidence run following
`setup-windows-host.md`; macOS remains explicitly deferred.
