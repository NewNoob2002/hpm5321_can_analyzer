#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
preset=${1:-hpm5321-flash-debug}
memory_budget_profile=product
case "$preset" in
    hpm5321-flash-debug|hpm5321-flash-release|hpm5321-flash-release-fs|hpm5321-flash-release-500k-preflight|hpm5321-ram-debug) ;;
    hpm5321-ram-debug-bus-off) memory_budget_profile=bus-off-debug ;;
    *) echo "unsupported preset: $preset" >&2; exit 2 ;;
esac

"$ROOT/scripts/env/check.sh"
cd "$ROOT"
CCACHE_DISABLE=1 cmake --preset "$preset"
CCACHE_DISABLE=1 cmake --build --preset "$preset"
python3 "$ROOT/scripts/env/normalize_build_paths.py" "$preset"
python3 "$ROOT/scripts/env/check_memory_budget.py" \
    --profile "$memory_budget_profile" \
    "$ROOT/build/$preset/output/demo.map"
python3 "$ROOT/scripts/env/write_build_manifest.py" "$preset"
