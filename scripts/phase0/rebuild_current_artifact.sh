#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
: "${HPM_SDK_BASE:?HPM_SDK_BASE must name the locked SDK checkout}"

expected_sdk=$(sed -n 's/^current_build_commit=//p' "$ROOT/dependencies/hpm-sdk.lock")
sdk_bytecode=$(find "$HPM_SDK_BASE" \
    \( -name __pycache__ -o -name '*.pyc' -o -name '*.pyo' \) \
    -print -quit)
[ -z "$sdk_bytecode" ] || {
    echo "SDK worktree contains Python bytecode: $sdk_bytecode" >&2
    exit 1
}
actual_sdk=$(git -C "$HPM_SDK_BASE" rev-parse HEAD)
[ "$actual_sdk" = "$expected_sdk" ] || {
    echo "SDK commit mismatch: expected $expected_sdk, got $actual_sdk" >&2
    exit 1
}
sdk_status=$(git -C "$HPM_SDK_BASE" status --porcelain --untracked-files=all)
[ -z "$sdk_status" ] || {
    echo "SDK worktree must be clean before rebuild" >&2
    exit 1
}

build="$ROOT/build/review-mcan-tx"
attestation="$ROOT/docs/evidence/phase0/T-CAN-TX-current-artifact.json"
source_commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_commit"])' "$attestation")
archive=$(mktemp -d)
trap 'rm -rf "$archive"' EXIT HUP INT TERM
git -C "$ROOT" archive "$source_commit" | tar -x -C "$archive"

cmake -E remove_directory "$build"
PYTHONDONTWRITEBYTECODE=1 CCACHE_DISABLE=1 cmake \
    -S "$archive/tools/phase0/mcan0_external_probe" -B "$build" -G Ninja \
    -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$archive/boards" \
    -DHPM_BUILD_TYPE=flash_xip -DCMAKE_BUILD_TYPE=Debug \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DMCAN0_ACTIVE_TX=1 -DMCAN0_REQUIRE_RX=0 -DMCAN0_ACK_RX=0
PYTHONDONTWRITEBYTECODE=1 CCACHE_DISABLE=1 cmake --build "$build" -j8
python3 "$ROOT/scripts/phase0/package_current_artifact.py" \
    "$attestation" --source-tree "$archive"
python3 - "$attestation" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

attestation = Path(sys.argv[1])
data = json.loads(attestation.read_text())
package = attestation.parents[3] / data["artifact_package"]
data["artifact_package_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
attestation.write_text(json.dumps(data, indent=2) + "\n")
PY
python3 "$ROOT/scripts/phase0/validate_current_artifact.py" \
    "$attestation"
