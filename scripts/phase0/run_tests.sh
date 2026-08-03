#!/usr/bin/env sh
set -eu
: "${HPM_SDK_BASE:?HPM_SDK_BASE is required; artifact tests may not be skipped}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
"$ROOT/scripts/phase0/rebuild_current_artifact.sh"
python3 -m unittest discover -s "$ROOT/tests" -t "$ROOT" -v
