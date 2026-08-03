# T-DEV-001/002/003 Official SDK Clean Build Report

Date: 2026-08-03
Source revision: `1ebcfa39` (`protocol: add control and diagnostics payloads`)
SDK: **official release commit** `12bd92495abeed7f0a908c589e60974267c0506b`
(hpm_sdk v1.12.1, per `dependencies/hpm-sdk.lock` `release_commit`)
Toolchain: GCC 13.2.0; CMake 4.2.3; Ninja 1.13.2

This closes the Gate A blocker recorded in `docs/development/phase1-status.md`:
the previous validated artifact was built from the fork commit `88b01b43…`. The
official release commit is a 24-commit ancestor of that fork whose delta is
documentation-only; this report provides the required clean-build evidence
against the official commit.

## Method

1. Cloned the local SDK repository to `/tmp/hpm_sdk_official` and checked out
   the locked official commit (no network):

   ```sh
   git clone /home/gtc/HPMicro/sdk/hpm_sdk /tmp/hpm_sdk_official
   git -C /tmp/hpm_sdk_official checkout 12bd92495abeed7f0a908c589e60974267c0506b
   ```

2. Removed the previous fork-based `build/` tree so all three presets configure
   and compile from empty binary directories.
3. Ran the standard build contract with the official SDK:

   ```sh
   HPM_SDK_BASE=/tmp/hpm_sdk_official \
   GNURISCV_TOOLCHAIN_PATH=/home/gtc/HPMicro/toolchain \
   scripts/build.sh hpm5321-flash-debug
   scripts/build.sh hpm5321-flash-release
   scripts/build.sh hpm5321-ram-debug
   ```

   `scripts/env/check.sh` classified the SDK as `official-release` and passed.

## Results

| Preset | ELF SHA-256 | ELF/BIN/MAP | compile_commands | source_dirty | Result |
|---|---|---|---:|---:|---:|
| Flash Debug | `c1c67a8c7c4e4a8b3cfca0303fc96b79f0b150f2ade454820393bc54657868a7` | present | present | false | PASS |
| Flash Release | `3d615e99e13effdc9abe819a3d4f8010dc50a95cd36fd63b44c9b539a944f4ce` | present | present | false | PASS |
| RAM Debug | `9b8a4af9153f865b1317e7a7a8eb165734af1ec6c1c8e57f3e27a1eb30386cbe` | present | present | false | PASS |

Artifacts: `docs/evidence/phase1/official-sdk-<preset>-build-manifest.json`
(ELF/BIN/MAP sizes and full SHA-256) and
`docs/evidence/phase1/official-sdk-<preset>-clean-build.txt` (full configure +
compile logs; 72 compile units each).

## Verdict

Linux official-SDK clean build lane **PASS**. The four Phase 0 hardware no-go
conditions and the Windows packaging gate are unaffected by this closure.
