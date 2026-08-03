# T-DEV-001/002/003 Linux Clean Build Report

Date: 2026-08-03
Source revision: `665ec887`
SDK: validated fork commit `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`
Toolchain: GCC 13.2.0; CMake 4.2.3; Ninja 1.13.2

A fresh local clone at `/tmp/hpm5321-phase1a-clean` executed:

```sh
scripts/build.sh hpm5321-flash-debug
scripts/build.sh hpm5321-flash-release
scripts/build.sh hpm5321-ram-debug
HPM_SDK_BASE=/home/gtc/HPMicro/sdk/hpm_sdk scripts/phase0/run_tests.sh
```

| Preset | ELF SHA-256 prefix | ELF/BIN/MAP | compile_commands | Result |
|---|---|---:|---:|---:|
| Flash Debug | `9260a206bfd3b6e9` | present | present | PASS |
| Flash Release | `49c9dc55951272bb` | present | present | PASS |
| RAM Debug | `88511fc6725607b6` | present | present | PASS |

All three manifests report `source_dirty=false`; full sizes and hashes are in
this directory. The standard self-contained suite rebuilt the ABI-v5 attested
probe and passed 17/17 tests.

Verdict: Linux T-DEV-001/002/003 build lane **PASS**. This does not close the
Windows/macOS, VSCode UI debug, OpenOCD or official-SDK gates.
