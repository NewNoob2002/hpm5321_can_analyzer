#!/usr/bin/env python3
"""Normalize checkout-specific text in linker map artifacts."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def normalized_text(text: str, build: Path) -> str:
    mappings = [
        (build.resolve(), Path("/build/hpm5321_can_analyzer")),
        (ROOT.resolve(), Path("/src/hpm5321_can_analyzer")),
    ]
    for variable, replacement in (
        ("HPM_SDK_BASE", "/sdk/hpm_sdk"),
        ("GNURISCV_TOOLCHAIN_PATH", "/toolchain/riscv"),
    ):
        value = os.environ.get(variable)
        if value:
            mappings.append((Path(value).resolve(), Path(replacement)))
    for source, replacement in sorted(mappings, key=lambda item: len(str(item[0])), reverse=True):
        text = text.replace(str(source), str(replacement))
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: normalize_build_paths.py PRESET")
    build = ROOT / "build" / argv[1]
    map_path = build / "output/demo.map"
    original = map_path.read_text(errors="surrogateescape")
    normalized = normalized_text(original, build)
    map_path.write_text(normalized, errors="surrogateescape")
    print(f"PASS normalized-map={map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
