# Linux Development Setup

## Environment contract

Export paths outside the repository; never commit personal absolute paths:

```sh
export HPM_SDK_BASE=/path/to/hpm_sdk
export GNURISCV_TOOLCHAIN_PATH=/path/to/riscv-toolchain
```

The accepted SDK commits are recorded in `dependencies/hpm-sdk.lock`.
`scripts/env/check.sh` rejects any other checkout. The validated fork supports
artifact-specific hardware work; the official v1.12.1 three-preset clean build
has separate PASS evidence and is the Gate A reproducibility baseline.

## Build

```sh
scripts/build.sh hpm5321-flash-debug
scripts/build.sh hpm5321-flash-release
scripts/build.sh hpm5321-ram-debug
```

Each build emits `demo.elf`, `demo.bin`, `demo.map`, `compile_commands.json`
and `build-manifest.json` below `build/<preset>/`. The manifest records Git and
SDK revisions, compiler identity, sizes and SHA-256 values.

VSCode tasks call only these scripts/presets. clangd reads the Flash Debug
compilation database. Start J-Link GDB Server separately with target
`HPM5321xCFx`, JTAG 4 MHz, port 2331, then use the checked-in attach profile.
Flashing remains a safety-preflight operation and is not part of a build task.

## Verification

```sh
HPM_SDK_BASE="$HPM_SDK_BASE" scripts/phase0/run_tests.sh
```

Phase 1B is closed by the aggregate manifest in
`docs/evidence/phase1/phase1b-closure.json`; this Linux procedure is one input,
not the sole closure proof. macOS remains outside the current CLI scope.
