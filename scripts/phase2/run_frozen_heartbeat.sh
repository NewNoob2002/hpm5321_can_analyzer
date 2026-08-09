#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FROZEN_ELF_SHA256="c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2"
P2_FROZEN_ELF="${P2_FROZEN_ELF:-${ROOT}/build/p2-frozen-980a38c/demo.elf}"
DURATION_SECONDS="${1:-86400}"
RUN_DATE="$(date +%F)"
OUTPUT="${2:-${ROOT}/docs/evidence/phase2/T-RTOS-003-${DURATION_SECONDS}-${RUN_DATE}.json}"

if (( $# > 2 )); then
    printf 'usage: %s [duration-seconds] [output-json]\n' "$0" >&2
    exit 2
fi

if [[ -n "${GNURISCV_TOOLCHAIN_PATH:-}" ]]; then
    GDB="${GNURISCV_TOOLCHAIN_PATH}/bin/riscv32-unknown-elf-gdb"
else
    GDB="$(command -v riscv32-unknown-elf-gdb || true)"
fi
GDB_SERVER="$(command -v JLinkGDBServerCLExe || true)"

if [[ ! -x "${GDB}" ]]; then
    printf 'riscv32-unknown-elf-gdb not found; set GNURISCV_TOOLCHAIN_PATH or PATH\n' >&2
    exit 2
fi
if [[ -z "${GDB_SERVER}" ]]; then
    printf 'JLinkGDBServerCLExe not found in PATH\n' >&2
    exit 2
fi

exec python3 "${ROOT}/scripts/phase2/collect_heartbeat.py" \
    --test-id T-RTOS-003 \
    --elf "${P2_FROZEN_ELF}" \
    --expected-elf-sha256 "${FROZEN_ELF_SHA256}" \
    --output "${OUTPUT}" \
    --duration-seconds "${DURATION_SECONDS}" \
    --interval-seconds "${INTERVAL_SECONDS:-60}" \
    --gdb "${GDB}" \
    --gdb-server "${GDB_SERVER}"
