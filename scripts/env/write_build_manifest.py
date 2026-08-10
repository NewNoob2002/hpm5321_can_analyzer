#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
preset = sys.argv[1]
build = ROOT / "build" / preset
output = build / "output"

artifacts = {}
for suffix in ("elf", "bin", "map"):
    path = output / f"demo.{suffix}"
    if not path.is_file():
        raise SystemExit(f"missing build artifact: {path}")
    artifacts[path.name] = {
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

compile_db = build / "compile_commands.json"
if not compile_db.is_file():
    raise SystemExit("compile_commands.json was not generated")

sdk = Path(os.environ["HPM_SDK_BASE"]).resolve()
cache = (build / "CMakeCache.txt").read_text().splitlines()


def cache_value(name: str) -> str:
    prefix = f"{name}:"
    return next(
        line.split("=", 1)[1]
        for line in cache
        if line.startswith(prefix) and "=" in line
    )


compiler_path = next(
    line.split("=", 1)[1]
    for line in cache
    if line.startswith(("CMAKE_C_COMPILER:FILEPATH=", "CMAKE_C_COMPILER:STRING="))
)
data = {
    "schema": 1,
    "preset": preset,
    "source_revision": subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip(),
    "source_dirty": bool(subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip()),
    "sdk_commit": subprocess.check_output(
        ["git", "-C", str(sdk), "rev-parse", "HEAD"], text=True
    ).strip(),
    "compiler": subprocess.check_output(
        [compiler_path, "--version"],
        text=True,
    ).splitlines()[0],
    "build_options": {
        "APP_USB_FORCE_FULL_SPEED": cache_value("APP_USB_FORCE_FULL_SPEED") == "ON",
    },
    "compile_commands_sha256": hashlib.sha256(compile_db.read_bytes()).hexdigest(),
    "artifacts": artifacts,
}
(build / "build-manifest.json").write_text(json.dumps(data, indent=2) + "\n")
print(f"PASS manifest={build / 'build-manifest.json'}")
