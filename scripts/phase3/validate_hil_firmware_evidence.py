#!/usr/bin/env python3
"""Validate immutable P3B firmware program/verify/readback evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(
    "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = (
    "package-manifest.json",
    "build/build-manifest.json",
    "firmware/demo.elf",
    "firmware/demo.bin",
)
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_ELF_BYTES = 1024 * 1024
MAX_BIN_BYTES = 1024 * 1024
MATCHED_SECTION_RE = re.compile(
    r"^Section (?P<name>\S+), range 0x[0-9a-fA-F]+ -- 0x[0-9a-fA-F]+: matched\.$"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"invalid {label}")
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        errors.append(f"invalid {label}")
        return None
    if str(path) != value:
        errors.append(f"invalid {label}")
        return None
    return value


def repository_file(
    root: Path, relative: object, label: str, errors: list[str]
) -> Path | None:
    value = safe_relative_path(relative, label, errors)
    if value is None:
        return None
    path = root / value
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError):
        errors.append(f"invalid or missing {label}: {value}")
        return None
    if path.is_symlink() or not resolved.is_file():
        errors.append(f"{label} must be a regular repository file")
        return None
    return resolved


def json_object(data: bytes, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return None
    return value


def archived_lock_value(root: Path, commit: str, errors: list[str]) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:dependencies/hpm-sdk.lock"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        errors.append("source commit does not contain dependencies/hpm-sdk.lock")
        return None
    try:
        lines = result.stdout.decode().splitlines()
    except UnicodeDecodeError:
        errors.append("archived SDK lock is not UTF-8")
        return None
    prefix = "current_build_commit="
    for line in lines:
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    errors.append("archived SDK lock is missing current_build_commit")
    return None


def validate_zip_info(info: zipfile.ZipInfo, expected: str, errors: list[str]) -> None:
    safe_relative_path(info.filename, "package member", errors)
    if info.filename != expected:
        errors.append("firmware package member list mismatch")
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
        errors.append(f"firmware package member metadata mismatch: {info.filename}")


def marker(text: str, name: str, errors: list[str]) -> str | None:
    prefix = f"{name} "
    values = [line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        errors.append(f"transcript requires exactly one {name} marker")
        return None
    return values[0]


def validate(root: Path, manifest_relative: Path = DEFAULT_MANIFEST) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    manifest_path = repository_file(root, manifest_relative.as_posix(), "evidence manifest", errors)
    if manifest_path is None:
        return errors
    if manifest_path.stat().st_size > MAX_JSON_BYTES:
        return ["evidence manifest exceeds size limit"]
    evidence = json_object(manifest_path.read_bytes(), "evidence manifest", errors)
    if evidence is None:
        return errors

    if evidence.get("schema") != 1:
        errors.append("unsupported evidence manifest schema")
    if evidence.get("evidence_id") != "P3B-HIL-firmware-2026-08-14":
        errors.append("unexpected evidence ID")
    if evidence.get("phase") != "P3B":
        errors.append("evidence phase must be P3B")
    if evidence.get("scope") != "firmware_program_verify_and_flash_readback":
        errors.append("unexpected evidence scope")
    if evidence.get("status") != "PASS":
        errors.append("firmware evidence is not PASS")
    if evidence.get("qualification_status") != "PARTIAL":
        errors.append("P3B qualification must remain PARTIAL")
    if evidence.get("p4e_gate") != "BLOCKED":
        errors.append("P4E gate must remain BLOCKED")

    source = evidence.get("source")
    source_commit = source.get("commit") if isinstance(source, dict) else None
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        errors.append("evidence requires a full source commit")
    if not isinstance(source, dict) or source.get("dirty") is not False:
        errors.append("evidence source dirty must be false")

    sdk = evidence.get("sdk")
    sdk_commit = sdk.get("commit") if isinstance(sdk, dict) else None
    if not isinstance(sdk_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", sdk_commit):
        errors.append("evidence requires a full SDK commit")
    if isinstance(source_commit, str) and re.fullmatch(r"[0-9a-f]{40}", source_commit):
        locked_sdk = archived_lock_value(root, source_commit, errors)
        if locked_sdk is not None and sdk_commit != locked_sdk:
            errors.append("SDK commit does not match archived source lock")

    toolchain = evidence.get("toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("compiler"), str):
        errors.append("evidence requires compiler")
    build = evidence.get("build")
    if not isinstance(build, dict):
        errors.append("evidence requires build")
        build = {}
    if build.get("preset") != "hpm5321-flash-release":
        errors.append("unexpected build preset")
    options = build.get("options")
    if not isinstance(options, dict) or options.get("APP_MCAN_BITRATE") != 1_000_000:
        errors.append("P3B evidence requires APP_MCAN_BITRATE=1000000")

    package = evidence.get("package")
    if not isinstance(package, dict):
        errors.append("evidence requires package")
        return errors
    package_path = repository_file(root, package.get("path"), "firmware package", errors)
    if package_path is None:
        return errors
    if not 0 < package_path.stat().st_size <= MAX_PACKAGE_BYTES:
        errors.append("firmware package size is invalid")
    if package.get("size") != package_path.stat().st_size:
        errors.append("firmware package size mismatch")
    if package.get("sha256") != sha256_file(package_path):
        errors.append("firmware package SHA-256 mismatch")
    if package.get("members") != list(PACKAGE_MEMBERS):
        errors.append("evidence package member list mismatch")

    member_bytes: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append("firmware package archive comment is not allowed")
            if archive.namelist() != list(PACKAGE_MEMBERS):
                errors.append("firmware package member list mismatch")
            infos = archive.infolist()
            for info, expected in zip(infos, PACKAGE_MEMBERS, strict=False):
                validate_zip_info(info, expected, errors)
            size_limits = (MAX_JSON_BYTES, MAX_JSON_BYTES, MAX_ELF_BYTES, MAX_BIN_BYTES)
            for info, limit in zip(infos, size_limits, strict=False):
                if not 0 < info.file_size <= limit:
                    errors.append(f"firmware package member size is invalid: {info.filename}")
            for name in PACKAGE_MEMBERS:
                member_bytes[name] = archive.read(name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid firmware package: {exc}")
        return errors

    package_manifest_bytes = member_bytes["package-manifest.json"]
    if package.get("package_manifest_sha256") != sha256_bytes(package_manifest_bytes):
        errors.append("package manifest SHA-256 mismatch")
    package_manifest = json_object(package_manifest_bytes, "package manifest", errors)
    archived_build = json_object(
        member_bytes["build/build-manifest.json"], "archived build manifest", errors
    )
    if package_manifest is None or archived_build is None:
        return errors
    if package_manifest.get("schema") != 1:
        errors.append("unsupported package manifest schema")

    required_package_values = {
        "source": source,
        "sdk": sdk,
        "toolchain": toolchain,
        "build": {
            "preset": build.get("preset"),
            "options": options,
            "compile_commands_sha256": archived_build.get("compile_commands_sha256"),
            "manifest_sha256": sha256_bytes(member_bytes["build/build-manifest.json"]),
            "manifest_size": len(member_bytes["build/build-manifest.json"]),
        },
        "firmware": evidence.get("firmware"),
    }
    for name, expected in required_package_values.items():
        if package_manifest.get(name) != expected:
            errors.append(f"package manifest mismatch: {name}")

    archived_required = {
        "schema": 1,
        "source_revision": source_commit,
        "source_dirty": False,
        "sdk_commit": sdk_commit,
        "compiler": toolchain.get("compiler") if isinstance(toolchain, dict) else None,
        "preset": build.get("preset"),
        "build_options": options,
    }
    for name, expected in archived_required.items():
        if archived_build.get(name) != expected:
            errors.append(f"archived build manifest mismatch: {name}")
    if build.get("manifest_member") != "build/build-manifest.json":
        errors.append("unexpected archived build manifest member")
    build_digest = sha256_bytes(member_bytes["build/build-manifest.json"])
    if build.get("manifest_sha256") != build_digest:
        errors.append("archived build manifest SHA-256 mismatch")

    firmware = evidence.get("firmware")
    if not isinstance(firmware, dict):
        errors.append("evidence requires firmware")
        firmware = {}
    archived_artifacts = archived_build.get("artifacts")
    if not isinstance(archived_artifacts, dict):
        errors.append("archived build manifest requires artifacts")
        archived_artifacts = {}
    for name, member in (
        ("demo.elf", "firmware/demo.elf"),
        ("demo.bin", "firmware/demo.bin"),
    ):
        actual = {
            "sha256": sha256_bytes(member_bytes[member]),
            "size": len(member_bytes[member]),
        }
        if firmware.get(name) != actual:
            errors.append(f"firmware evidence mismatch: {name}")
        if archived_artifacts.get(name) != actual:
            errors.append(f"archived build artifact mismatch: {name}")
    elf_record = firmware.get("demo.elf")
    elf_sha256 = elf_record.get("sha256") if isinstance(elf_record, dict) else None

    target = evidence.get("target")
    if not isinstance(target, dict):
        errors.append("evidence requires target")
        target = {}
    if target.get("probe_serial") != "607000454":
        errors.append("unexpected J-Link probe serial")
    if target.get("device") != "HPM5321xCFx":
        errors.append("unexpected target device")
    if target.get("interface") != "JTAG" or target.get("speed_khz") != 4000:
        errors.append("unexpected target interface configuration")

    program = evidence.get("program_verify")
    readback = evidence.get("flash_readback")
    for record, label in ((program, "program transcript"), (readback, "compare transcript")):
        if not isinstance(record, dict) or record.get("status") != "PASS":
            errors.append(f"{label} status is not PASS")
    program_record = program if isinstance(program, dict) else {}
    readback_record = readback if isinstance(readback, dict) else {}
    program_transcript = program_record.get("transcript", {})
    readback_transcript = readback_record.get("transcript", {})
    program_path = repository_file(
        root,
        program_transcript.get("path") if isinstance(program_transcript, dict) else None,
        "program transcript",
        errors,
    )
    readback_path = repository_file(
        root,
        readback_transcript.get("path") if isinstance(readback_transcript, dict) else None,
        "compare transcript",
        errors,
    )
    if program_path is not None:
        if program_transcript.get("sha256") != sha256_file(program_path):
            errors.append("program transcript SHA-256 mismatch")
        program_text = program_path.read_text(encoding="utf-8")
        if marker(program_text, "P3B_HIL_PROBE_SERIAL", errors) != target.get(
            "probe_serial"
        ):
            errors.append("program transcript probe serial mismatch")
        if marker(program_text, "P3B_HIL_TARGET", errors) != target.get("device"):
            errors.append("program transcript target mismatch")
        if marker(program_text, "P3B_HIL_BUILD_MANIFEST_SHA256", errors) != build_digest:
            errors.append("program transcript build manifest SHA-256 mismatch")
        if marker(program_text, "P3B_HIL_ELF_SHA256", errors) != elf_sha256:
            errors.append("program transcript ELF SHA-256 mismatch")
        if "Program & Verify speed:" not in program_text or "\nO.K.\n" not in program_text:
            errors.append("program transcript does not prove Program + Verify success")

    if readback_path is not None:
        if readback_transcript.get("sha256") != sha256_file(readback_path):
            errors.append("compare transcript SHA-256 mismatch")
        readback_text = readback_path.read_text(encoding="utf-8")
        if marker(readback_text, "P3B_HIL_PROBE_SERIAL", errors) != target.get(
            "probe_serial"
        ):
            errors.append("compare transcript probe serial mismatch")
        if marker(readback_text, "P3B_HIL_TARGET", errors) != target.get("device"):
            errors.append("compare transcript target mismatch")
        if marker(readback_text, "P3B_HIL_ELF_SHA256", errors) != elf_sha256:
            errors.append("compare transcript ELF SHA-256 mismatch")
        sections = [
            match.group("name")
            for line in readback_text.splitlines()
            if (match := MATCHED_SECTION_RE.fullmatch(line))
        ]
        if readback_record.get("matched_sections") != sections:
            errors.append("compare transcript matched section list mismatch")
        required_sections = {
            ".nor_cfg_option",
            ".boot_header",
            ".start",
            ".vectors",
            ".text",
            ".data",
        }
        if not required_sections.issubset(sections):
            errors.append("compare transcript is missing required matched sections")
        if ": MIS-MATCHED!" in readback_text:
            errors.append("compare transcript reports a mismatched section")

    boundary = evidence.get("evidence_boundary")
    pending = boundary.get("pending") if isinstance(boundary, dict) else None
    required_pending = [
        "1 Mbit/s external CAN generator run at >=6000 frame/s for 1800 seconds",
        "independent analyzer timestamp and bit-timing reconciliation",
        "USB backpressure under CAN load",
        "state-edge/drop reconciliation",
        "physical USB disconnect/reconnect",
        "bus-off/manual fault injection",
    ]
    if pending != required_pending:
        errors.append("evidence boundary pending set mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    errors = validate(args.root, args.manifest)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS immutable P3B firmware program/verify/readback evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
