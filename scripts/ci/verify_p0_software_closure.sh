#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"

python3 scripts/ci/run_python_tests.py
python3 scripts/phase0/validate_current_artifact.py \
    docs/evidence/phase0/T-CAN-TX-current-artifact.json
python3 scripts/phase3/validate_hil_firmware_evidence.py
python3 scripts/phase3/validate_p3b_execution_status.py
python3 scripts/phase3/validate_p3b_load_evidence.py
python3 scripts/phase3/validate_p3b_analyzer_evidence.py
python3 scripts/phase3/validate_p3b_backpressure_evidence.py
python3 scripts/phase3/validate_p3b_bus_off_attempt.py
python3 scripts/phase3/validate_p3b_bus_off_evidence.py
python3 scripts/phase3/validate_p3b_current_status.py

scripts/build.sh hpm5321-flash-release
scripts/build.sh hpm5321-ram-debug-bus-off
python3 scripts/ci/check_reproducible_build_contract.py \
    build/hpm5321-flash-release/compile_commands.json \
    build/hpm5321-ram-debug-bus-off/compile_commands.json
python3 scripts/env/check_mcan0_hook_isolation.py \
    --release-build build/hpm5321-flash-release \
    --debug-build build/hpm5321-ram-debug-bus-off

cargo check --manifest-path host/Cargo.toml --workspace --all-targets --locked
cargo test --manifest-path host/Cargo.toml --workspace --release --locked

printf '%s\n' 'PASS P0 software closure candidate'
