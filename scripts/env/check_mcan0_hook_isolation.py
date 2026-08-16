#!/usr/bin/env python3
"""Verify the P3B bus-off test ABI is isolated in actual firmware ELFs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


ABI_SYMBOL_SIZES = {
    "g_app_mcan0_bus_off_test_mailbox": 32,
    "g_app_mcan0_bus_off_test_result": 104,
}
SOURCE_SUFFIX = "USER/src/app_mcan0_owner.c"


def fail(message: str) -> None:
    raise SystemExit(message)


def cache_value(build: Path, name: str) -> str:
    prefix = f"{name}:"
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        if line.startswith(prefix) and "=" in line:
            return line.split("=", 1)[1]
    fail(f"{build}: CMake cache is missing {name}")
    raise AssertionError


def compile_definition(build: Path, name: str) -> str:
    commands = json.loads((build / "compile_commands.json").read_text())
    entry = next(
        (item for item in commands if item.get("file", "").endswith(SOURCE_SUFFIX)),
        None,
    )
    if entry is None:
        fail(f"{build}: owner compile command is missing")
    arguments = entry.get("arguments")
    if arguments is None:
        arguments = shlex.split(entry["command"])
    pattern = re.compile(rf"^-D{re.escape(name)}=(.+)$")
    values = [match.group(1) for token in arguments if (match := pattern.match(token))]
    if len(values) != 1:
        fail(f"{build}: compile command must define {name} exactly once")
    return values[0]


def nm_symbols(elf: Path, nm: str) -> dict[str, int]:
    output = subprocess.check_output(
        [nm, "-S", "--defined-only", str(elf)], text=True
    )
    symbols: dict[str, int] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            try:
                symbols[fields[3]] = int(fields[1], 16)
            except ValueError:
                continue
    return symbols


def verify_build(build: Path, enabled: bool, nm: str) -> None:
    elf = build / "output/demo.elf"
    if not elf.is_file():
        fail(f"missing firmware ELF: {elf}")
    expected_cache = "ON" if enabled else "OFF"
    expected_define = "1" if enabled else "0"
    if cache_value(build, "APP_MCAN0_BUS_OFF_TEST_HOOK") != expected_cache:
        fail(f"{build}: APP_MCAN0_BUS_OFF_TEST_HOOK cache mismatch")
    if compile_definition(build, "APP_MCAN0_BUS_OFF_TEST_HOOK") != expected_define:
        fail(f"{build}: APP_MCAN0_BUS_OFF_TEST_HOOK compile definition mismatch")

    symbols = nm_symbols(elf, nm)
    hook_symbols = {name: size for name, size in symbols.items() if "mcan0_bus_off_test" in name}
    if not enabled and hook_symbols:
        fail(f"{elf}: Release image leaks bus-off test symbols: {sorted(hook_symbols)}")
    if enabled:
        for name, expected_size in ABI_SYMBOL_SIZES.items():
            if symbols.get(name) != expected_size:
                fail(
                    f"{elf}: {name} size mismatch: "
                    f"expected {expected_size}, got {symbols.get(name)}"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-build", type=Path, required=True)
    parser.add_argument("--debug-build", type=Path, required=True)
    parser.add_argument("--nm")
    args = parser.parse_args()

    nm = args.nm
    if nm is None:
        toolchain = os.environ.get("GNURISCV_TOOLCHAIN_PATH")
        candidate = (
            str(Path(toolchain) / "bin/riscv32-unknown-elf-nm")
            if toolchain
            else None
        )
        nm = candidate if candidate and Path(candidate).is_file() else shutil.which("riscv32-unknown-elf-nm")
    if not nm:
        fail("riscv32-unknown-elf-nm is required")

    verify_build(args.release_build.resolve(), False, nm)
    verify_build(args.debug_build.resolve(), True, nm)
    print(
        "PASS MCAN0 bus-off hook isolated "
        f"release={args.release_build} debug={args.debug_build}"
    )


if __name__ == "__main__":
    main()
