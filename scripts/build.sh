#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
preset=${1:-hpm5321-flash-debug}
case "$preset" in
    hpm5321-flash-debug|hpm5321-flash-release|hpm5321-ram-debug) ;;
    *) echo "unsupported preset: $preset" >&2; exit 2 ;;
esac

"$ROOT/scripts/env/check.sh"
cd "$ROOT"
CCACHE_DISABLE=1 cmake --preset "$preset"
CCACHE_DISABLE=1 cmake --build --preset "$preset"
python3 "$ROOT/scripts/env/write_build_manifest.py" "$preset"
