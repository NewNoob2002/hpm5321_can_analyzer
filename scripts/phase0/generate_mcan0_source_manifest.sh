#!/usr/bin/env sh
set -eu
export LC_ALL=C
find \
  boards/hpm5321_custom \
  tools/phase0/mcan0_external_probe \
  -type f ! -name SHA256SUMS -print \
  | sort \
  | xargs sha256sum
sha256sum dependencies/hpm-sdk.lock CMakePresets.json
