#!/usr/bin/env python3
"""Validate the current MCAN probe artifact attestation."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

from validate_can_capture import (
    ROOT,
    sha256_file,
    verify_archived_source_manifest,
)

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ELF_BYTES = 4 * 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(message)


def safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        fail(f"invalid {label}")
    if str(path) != value:
        fail(f"invalid {label}")
    return value


def repository_file(relative: object, label: str) -> Path:
    relative = safe_relative_path(relative, label)
    path = ROOT / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError) as error:
        fail(f"invalid {label}")
        raise AssertionError from error
    if path.is_symlink() or not resolved.is_file():
        fail(f"{label} must be a regular repository file")
    return resolved


def archived_blob(commit: str, relative: str) -> bytes:
    relative = safe_relative_path(relative, "archived source path")
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        fail(f"archived source is missing at {commit}: {relative}")
    return result.stdout


def lock_value(lock: bytes, name: str) -> str:
    prefix = f"{name}="
    for line in lock.decode().splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    fail(f"archived SDK lock is missing {name}")
    raise AssertionError


def require_tool_string(package_manifest: dict, name: str) -> None:
    value = package_manifest.get(name)
    if not isinstance(value, str) or not value:
        fail(f"artifact package manifest requires {name}")


def validate_zip_member(info: zipfile.ZipInfo, expected_name: str) -> None:
    if info.filename != expected_name:
        fail("artifact package member list mismatch")
    safe_relative_path(info.filename, "artifact package member")
    if (
        info.date_time != FIXED_ZIP_TIME
        or info.create_system != 3
        or info.compress_type != zipfile.ZIP_STORED
        or info.flag_bits != 0
        or info.internal_attr != 0
        or info.external_attr != 0o100644 << 16
        or info.extra
        or info.comment
    ):
        fail(f"artifact package member metadata mismatch: {info.filename}")


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
    if data.get("schema") != 2:
        fail("current artifact attestation schema must be 2")
    if (data.get("result_abi_version", 0) >= 5 and
            data.get("external_capture_status") != "independent_results_only"):
        nonce = data.get("run_nonce")
        if not isinstance(nonce, int) or not 0 < nonce <= 0xFFFF:
            fail("ABI-v5 artifact attestation requires a 16-bit run_nonce")

    source_commit = data.get("source_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        fail("artifact attestation requires a full source_commit")
    manifest_digest = verify_archived_source_manifest(data)

    artifact_name = safe_relative_path(data.get("artifact"), "artifact member")
    package = repository_file(data.get("artifact_package"), "artifact package")
    if package.stat().st_size > MAX_PACKAGE_BYTES:
        fail("artifact package exceeds size limit")
    if sha256_file(package) != data.get("artifact_package_sha256"):
        fail("artifact package SHA-256 mismatch")
    expected_members = [
        "package-manifest.json",
        artifact_name,
    ]
    try:
        with zipfile.ZipFile(package) as archive:
            if archive.comment:
                fail("artifact package archive comment is not allowed")
            if archive.namelist() != expected_members:
                fail("artifact package member list mismatch")
            infos = archive.infolist()
            for info, expected_name in zip(infos, expected_members, strict=True):
                validate_zip_member(info, expected_name)
            if infos[0].file_size > MAX_MANIFEST_BYTES:
                fail("artifact package manifest exceeds size limit")
            if not 0 < infos[1].file_size <= MAX_ELF_BYTES:
                fail("artifact package ELF exceeds size limit")
            package_manifest = json.loads(archive.read("package-manifest.json"))
            artifact_bytes = archive.read(artifact_name)
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        fail(f"invalid artifact package: {error}")

    if hashlib.sha256(artifact_bytes).hexdigest() != data["elf_sha256"]:
        fail("artifact SHA-256 mismatch")

    required_package_values = {
        "schema": 2,
        "artifact": artifact_name,
        "elf_sha256": data.get("elf_sha256"),
        "elf_size": len(artifact_bytes),
        "source_commit": source_commit,
        "source_dirty": False,
        "source_manifest_sha256": data.get("source_manifest_sha256"),
        "sdk_commit": data.get("sdk_commit"),
        "sdk_build_version": data.get("sdk_build_version"),
        "result_abi_version": data.get("result_abi_version"),
    }
    for name, expected in required_package_values.items():
        if package_manifest.get(name) != expected:
            fail(f"artifact package manifest mismatch: {name}")
    build = package_manifest.get("build")
    if not isinstance(build, dict):
        fail("artifact package manifest requires build")
    expected_build = {
        "board": "hpm5321_custom",
        "hpm_build_type": "flash_xip",
        "definitions": data.get("build_definitions"),
    }
    if build != expected_build:
        fail("artifact package manifest mismatch: build")
    if package_manifest.get("sdk_dirty") is not False:
        fail("artifact package SDK worktree must be clean")
    compile_commands_sha256 = package_manifest.get("compile_commands_sha256")
    if not isinstance(compile_commands_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", compile_commands_sha256
    ):
        fail("artifact package manifest requires compile_commands_sha256")
    if package_manifest.get("compile_commands_hash_mode") != "paths-normalized-v1":
        fail("artifact package manifest requires compile_commands_hash_mode")
    for name in ("compiler", "linker", "objcopy", "cmake", "ninja"):
        require_tool_string(package_manifest, name)

    sdk_commit = data["sdk_commit"]
    locked_sdk_commit = lock_value(
        archived_blob(source_commit, "dependencies/hpm-sdk.lock"),
        "current_build_commit",
    )
    if sdk_commit != locked_sdk_commit:
        fail("SDK commit does not match archived lock")
    sdk_base_value = os.environ.get("HPM_SDK_BASE")
    if sdk_base_value:
        sdk_base = Path(sdk_base_value).resolve()
        local_sdk_commit = subprocess.run(
            ["git", "-C", str(sdk_base), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if local_sdk_commit != sdk_commit:
            fail("SDK commit mismatch")

    source_suffix = "tools/phase0/mcan0_external_probe/src/main.c"
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
        f"PASS package={data['artifact_package_sha256']} "
        f"artifact={data['elf_sha256']} manifest={manifest_digest} "
        f"source={source_commit} sdk={sdk_commit} abi={data['result_abi_version']}"
    )


if __name__ == "__main__":
    main()
