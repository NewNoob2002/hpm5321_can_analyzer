#!/usr/bin/env python3
"""Verify that firmware compile commands carry deterministic path maps."""

import json
import os
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KINDS = ("file", "macro", "debug")
REQUIRED_GROUPS = {
    "app": ("USER/src/", "protocol/v1/c/"),
    "easylogger": ("third_party/easylogger/",),
    "board": ("boards/hpm5321_custom/",),
}
STABLE_ROOTS = {
    "source": "/src/hpm5321_can_analyzer",
    "build": "/build/hpm5321_can_analyzer",
    "sdk": "/sdk/hpm_sdk",
    "toolchain": "/toolchain/riscv",
}


def verify_compile_database(path: Path) -> dict[str, int]:
    entries = json.loads(path.read_text())
    build = path.parent.resolve()
    required_sources = {
        "source": ROOT.resolve(),
        "build": build,
        "sdk": Path(os.environ["HPM_SDK_BASE"]).resolve(),
        "toolchain": Path(os.environ["GNURISCV_TOOLCHAIN_PATH"]).resolve(),
    }
    counts = {"all": 0, "sdk": 0, **{name: 0 for name in REQUIRED_GROUPS}}
    failures = []
    for entry in entries:
        source = Path(entry["file"])
        command = entry.get("command")
        arguments = shlex.split(command) if isinstance(command, str) else entry["arguments"]
        counts["all"] += 1
        try:
            source.resolve().relative_to(required_sources["sdk"])
        except ValueError:
            pass
        else:
            counts["sdk"] += 1
        for kind in KINDS:
            maps = {token for token in arguments if token.startswith(f"-f{kind}-prefix-map=")}
            for name, original in required_sources.items():
                expected = f"-f{kind}-prefix-map={original}={STABLE_ROOTS[name]}"
                if expected not in maps:
                    failures.append(f"{source}: missing exact {kind} {name} map")
        try:
            relative = source.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            continue
        groups = [name for name, prefixes in REQUIRED_GROUPS.items() if relative.startswith(prefixes)]
        if not groups:
            continue
        for group in groups:
            counts[group] += 1
    if counts["all"] == 0:
        failures.append("compile database has no translation units")
    if counts["sdk"] == 0:
        failures.append("compile database has no SDK translation units")
    for group, count in counts.items():
        if count == 0:
            failures.append(f"compile database has no {group} translation units")
    if failures:
        raise ValueError("; ".join(failures))
    return counts


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: check_reproducible_build_contract.py COMPILE_DB...")
    for value in argv[1:]:
        path = Path(value)
        counts = verify_compile_database(path)
        print(f"PASS reproducible-compile-contract path={path} coverage={counts}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValueError as error:
        raise SystemExit(f"FAIL reproducible compile contract: {error}") from error
