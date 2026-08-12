#!/usr/bin/env python3
"""Validate the current MCAN probe artifact attestation."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from validate_can_capture import (
    ROOT,
    sha256_file,
    verify_archived_source_manifest,
)


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("attestation", type=Path)
    args = parser.parse_args()
    data = json.loads(args.attestation.read_text())
    allowed_capture_status = {
        "target_pass_external_capture_pending",
        "target_and_external_pass",
        "independent_results_only",
    }
    if data.get("external_capture_status") not in allowed_capture_status:
        fail("invalid external_capture_status")
    if (data.get("result_abi_version", 0) >= 5 and
            data.get("external_capture_status") != "independent_results_only"):
        nonce = data.get("run_nonce")
        if not isinstance(nonce, int) or not 0 < nonce <= 0xFFFF:
            fail("ABI-v5 artifact attestation requires a 16-bit run_nonce")

    artifact = ROOT / data["artifact"]
    if not artifact.is_file() or sha256_file(artifact) != data["elf_sha256"]:
        fail("artifact SHA-256 mismatch")
    source_commit = data.get("source_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        fail("artifact attestation requires a full source_commit")
    manifest_digest = verify_archived_source_manifest(data)

    sdk_base_value = os.environ.get("HPM_SDK_BASE")
    if not sdk_base_value:
        fail("HPM_SDK_BASE is required")
    sdk_base = Path(sdk_base_value).resolve()
    sdk_commit = subprocess.run(
        ["git", "-C", str(sdk_base), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if sdk_commit != data["sdk_commit"]:
        fail("SDK commit mismatch")

    build_dir = artifact.parents[1]
    version_header = build_dir / "build_tmp/generated/include/hpm_sdk_version.h"
    version_text = version_header.read_text()
    match = re.search(r"^#define BUILD_VERSION\s+(\S+)$", version_text, re.MULTILINE)
    if match is None or match.group(1) != data["sdk_build_version"]:
        fail("SDK BUILD_VERSION mismatch")

    compile_db = json.loads((build_dir / "compile_commands.json").read_text())
    source_suffix = "tools/phase0/mcan0_external_probe/src/main.c"
    source_entry = next(
        (entry for entry in compile_db if entry["file"].endswith(source_suffix)), None
    )
    if source_entry is None:
        fail("probe source compile command is missing")
    command = source_entry.get("command", " ".join(source_entry.get("arguments", [])))
    for name, value in data["build_definitions"].items():
        if f"-D{name}={value}" not in command:
            fail(f"build definition mismatch: {name}")

    source_text = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{source_commit}:{source_suffix}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    abi_match = re.search(r"#define PROBE_RESULT_ABI_VERSION\s+\((\d+)U\)", source_text)
    if abi_match is None or int(abi_match.group(1)) != data["result_abi_version"]:
        fail("result ABI mismatch")

    print(
        f"PASS artifact={data['elf_sha256']} manifest={manifest_digest} "
        f"source={source_commit} sdk={sdk_commit} abi={data['result_abi_version']}"
    )


if __name__ == "__main__":
    main()
