#!/usr/bin/env sh
set -eu
export LC_ALL=C
find \
  boards/hpm5321_custom \
  tools/phase0/mcan0_external_probe \
  -type f ! -name SHA256SUMS -print \
  | sort \
  | xargs sha256sum
sha256sum \
  scripts/phase0/generate_mcan0_source_manifest.sh \
  scripts/phase0/rebuild_current_artifact.sh \
  dependencies/hpm-sdk.lock \
  CMakePresets.json
