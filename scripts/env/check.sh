#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
: "${HPM_SDK_BASE:?HPM_SDK_BASE must point to an HPM SDK checkout}"
: "${GNURISCV_TOOLCHAIN_PATH:?GNURISCV_TOOLCHAIN_PATH must point to the RISC-V toolchain}"

for tool in cmake ninja git python3; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "missing required tool: $tool" >&2
        exit 1
    }
done

[ -f "$HPM_SDK_BASE/cmake/hpm-sdk-config.cmake" ] || {
    echo "HPM_SDK_BASE is not an HPM SDK checkout: $HPM_SDK_BASE" >&2
    exit 1
}
[ -x "$GNURISCV_TOOLCHAIN_PATH/bin/riscv32-unknown-elf-gcc" ] || {
    echo "RISC-V compiler is missing under GNURISCV_TOOLCHAIN_PATH" >&2
    exit 1
}

sdk_commit=$(git -C "$HPM_SDK_BASE" rev-parse HEAD)
official=$(sed -n 's/^release_commit=//p' "$ROOT/dependencies/hpm-sdk.lock")
current=$(sed -n 's/^current_build_commit=//p' "$ROOT/dependencies/hpm-sdk.lock")
case "$sdk_commit" in
    "$official") sdk_class=official-release ;;
    "$current") sdk_class=validated-fork ;;
    *)
        echo "SDK commit is not locked: $sdk_commit" >&2
        exit 1
        ;;
esac

printf 'PASS sdk=%s class=%s cmake=%s ninja=%s\n' \
    "$sdk_commit" "$sdk_class" \
    "$(cmake --version | sed -n '1s/^cmake version //p')" \
    "$(ninja --version)"
