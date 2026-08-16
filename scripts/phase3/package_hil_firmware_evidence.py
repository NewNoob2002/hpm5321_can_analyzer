#!/usr/bin/env python3
"""Create deterministic firmware and flash/readback evidence for P3B HIL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = (
    "package-manifest.json",
    "build/build-manifest.json",
    "firmware/demo.elf",
    "firmware/demo.bin",
)
MATCHED_SECTION_RE = re.compile(
    r"^Section (?P<name>\S+), range 0x[0-9a-fA-F]+ -- 0x[0-9a-fA-F]+: matched\.$"
)


def fail(message: str) -> None:
    raise SystemExit(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value:
        fail(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        fail(f"invalid {label}")
    if str(path) != value:
        fail(f"invalid {label}")
    return value


def repository_output(relative: str, label: str) -> Path:
    relative = safe_relative_path(relative, label)
    path = ROOT / relative
    try:
        parent = path.parent.resolve(strict=True)
        parent.relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError) as exc:
        fail(f"invalid {label}")
        raise AssertionError from exc
    if parent != path.parent.absolute():
        fail(f"invalid {label}")
    if path.is_symlink():
        fail(f"{label} must not be a symlink")
    if path.exists() and not path.is_file():
        fail(f"{label} must be a regular file or absent")
    return path


def regular_file(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        fail(f"missing {label}: {path}")
        raise AssertionError from exc
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        fail(f"{label} must be a regular repository file")
        raise AssertionError from exc
    if path.is_symlink() or not resolved.is_file():
        fail(f"{label} must be a regular repository file")
    return resolved


def json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} root must be an object")
    return value


def git_blob(commit: str, relative: str) -> bytes:
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


def marker(text: str, name: str) -> str:
    prefix = f"{name} "
    values = [line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix)]
    if len(values) != 1 or not values[0]:
        fail(f"transcript requires exactly one {name} marker")
    return values[0]


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def normalized_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-manifest",
        type=Path,
        default=ROOT / "build/hpm5321-flash-release/build-manifest.json",
    )
    parser.add_argument(
        "--program-log",
        type=Path,
        default=ROOT / "docs/evidence/phase3/P3B-HIL-flash-jlink-2026-08-14.txt",
    )
    parser.add_argument(
        "--compare-log",
        type=Path,
        default=ROOT / "docs/evidence/phase3/P3B-HIL-flash-compare-gdb-2026-08-14.txt",
    )
    parser.add_argument(
        "--package",
        default="docs/evidence/phase3/P3B-HIL-firmware-afbf243.zip",
    )
    parser.add_argument(
        "--evidence",
        default="docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json",
    )
    args = parser.parse_args()

    build_manifest_path = regular_file(args.build_manifest, "build manifest")
    program_log_path = regular_file(args.program_log, "program transcript")
    compare_log_path = regular_file(args.compare_log, "compare transcript")
    package_path = repository_output(args.package, "firmware package output")
    evidence_path = repository_output(args.evidence, "evidence manifest output")
    if package_path == evidence_path:
        fail("firmware package and evidence outputs must be distinct")
    root_resolved = ROOT.resolve()

    def relative(path: Path) -> str:
        return path.relative_to(root_resolved).as_posix()

    for path in (
        build_manifest_path,
        program_log_path,
        compare_log_path,
        package_path,
        evidence_path,
    ):
        relative(path)

    build_manifest_bytes = build_manifest_path.read_bytes()
    build = json_object(build_manifest_path, "build manifest")
    if build.get("schema") != 1:
        fail("unsupported build manifest schema")
    source_commit = build.get("source_revision")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        fail("build manifest requires a full source revision")
    if build.get("source_dirty") is not False:
        fail("P3B HIL firmware evidence requires a clean source build")
    sdk_commit = build.get("sdk_commit")
    if not isinstance(sdk_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", sdk_commit):
        fail("build manifest requires a full SDK commit")
    locked_sdk_commit = lock_value(
        git_blob(source_commit, "dependencies/hpm-sdk.lock"), "current_build_commit"
    )
    if sdk_commit != locked_sdk_commit:
        fail("SDK commit does not match the archived source lock")
    compiler = build.get("compiler")
    if not isinstance(compiler, str) or not compiler:
        fail("build manifest requires compiler")
    if build.get("preset") != "hpm5321-flash-release":
        fail("unexpected build preset")
    build_options = build.get("build_options")
    if not isinstance(build_options, dict) or build_options.get("APP_MCAN_BITRATE") != 1_000_000:
        fail("P3B HIL firmware must use APP_MCAN_BITRATE=1000000")

    output_dir = build_manifest_path.parent / "output"
    firmware: dict[str, dict[str, Any]] = {}
    firmware_bytes: dict[str, bytes] = {}
    for name in ("demo.elf", "demo.bin"):
        path = regular_file(output_dir / name, name)
        data = path.read_bytes()
        declared = build.get("artifacts", {}).get(name)
        expected = {"sha256": sha256_bytes(data), "size": len(data)}
        if declared != expected:
            fail(f"build manifest artifact mismatch: {name}")
        firmware[name] = expected
        firmware_bytes[name] = data

    program_text = program_log_path.read_text(encoding="utf-8")
    compare_text = compare_log_path.read_text(encoding="utf-8")
    serial = marker(program_text, "P3B_HIL_PROBE_SERIAL")
    target = marker(program_text, "P3B_HIL_TARGET")
    if marker(program_text, "P3B_HIL_BUILD_MANIFEST_SHA256") != sha256_bytes(
        build_manifest_bytes
    ):
        fail("program transcript build manifest SHA-256 mismatch")
    if marker(program_text, "P3B_HIL_ELF_SHA256") != firmware["demo.elf"]["sha256"]:
        fail("program transcript ELF SHA-256 mismatch")
    if "Program & Verify speed:" not in program_text or "\nO.K.\n" not in program_text:
        fail("program transcript does not prove Program + Verify success")

    if marker(compare_text, "P3B_HIL_PROBE_SERIAL") != serial:
        fail("compare transcript probe serial mismatch")
    if marker(compare_text, "P3B_HIL_TARGET") != target:
        fail("compare transcript target mismatch")
    if marker(compare_text, "P3B_HIL_ELF_SHA256") != firmware["demo.elf"]["sha256"]:
        fail("compare transcript ELF SHA-256 mismatch")
    compare_timestamp = marker(compare_text, "P3B_HIL_COMPARE_DATE_UTC")
    matched_sections = [
        match.group("name")
        for line in compare_text.splitlines()
        if (match := MATCHED_SECTION_RE.fullmatch(line))
    ]
    required_sections = {".nor_cfg_option", ".boot_header", ".start", ".vectors", ".text", ".data"}
    if not required_sections.issubset(matched_sections):
        fail("compare transcript is missing required matched sections")
    if "Section " in compare_text and ": MIS-MATCHED!" in compare_text:
        fail("compare transcript reports a mismatched section")

    package_manifest = {
        "schema": 1,
        "source": {"commit": source_commit, "dirty": False},
        "sdk": {"commit": sdk_commit},
        "toolchain": {"compiler": compiler},
        "build": {
            "preset": build["preset"],
            "options": build_options,
            "compile_commands_sha256": build.get("compile_commands_sha256"),
            "manifest_sha256": sha256_bytes(build_manifest_bytes),
            "manifest_size": len(build_manifest_bytes),
        },
        "firmware": firmware,
    }
    package_manifest_bytes = normalized_json(package_manifest)
    member_bytes = {
        "package-manifest.json": package_manifest_bytes,
        "build/build-manifest.json": build_manifest_bytes,
        "firmware/demo.elf": firmware_bytes["demo.elf"],
        "firmware/demo.bin": firmware_bytes["demo.bin"],
    }
    with tempfile.NamedTemporaryFile(
        dir=package_path.parent,
        prefix=f".{package_path.name}.",
        delete=False,
    ) as stream:
        temporary_package = Path(stream.name)
    with tempfile.NamedTemporaryFile(
        dir=evidence_path.parent,
        prefix=f".{evidence_path.name}.",
        delete=False,
    ) as stream:
        temporary_evidence = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary_package, "w") as archive:
            archive.comment = b""
            for name in PACKAGE_MEMBERS:
                archive.writestr(zip_info(name), member_bytes[name])

        pending = [
            "1 Mbit/s external CAN generator run at >=6000 frame/s for 1800 seconds",
            "independent analyzer timestamp and bit-timing reconciliation",
            "USB backpressure under CAN load",
            "state-edge/drop reconciliation",
            "physical USB disconnect/reconnect",
            "bus-off/manual fault injection",
        ]
        evidence = {
            "schema": 1,
            "evidence_id": "P3B-HIL-firmware-2026-08-14",
            "phase": "P3B",
            "scope": "firmware_program_verify_and_flash_readback",
            "status": "PASS",
            "qualification_status": "PARTIAL",
            "p4e_gate": "BLOCKED",
            "captured_at_utc": compare_timestamp,
            "source": {"commit": source_commit, "dirty": False},
            "sdk": {"commit": sdk_commit},
            "toolchain": {"compiler": compiler},
            "build": {
                "preset": build["preset"],
                "options": build_options,
                "manifest_member": "build/build-manifest.json",
                "manifest_sha256": sha256_bytes(build_manifest_bytes),
            },
            "firmware": firmware,
            "package": {
                "path": relative(package_path),
                "sha256": sha256_file(temporary_package),
                "size": temporary_package.stat().st_size,
                "members": list(PACKAGE_MEMBERS),
                "package_manifest_sha256": sha256_bytes(package_manifest_bytes),
            },
            "target": {
                "probe_serial": serial,
                "device": target,
                "interface": "JTAG",
                "speed_khz": 4000,
            },
            "program_verify": {
                "status": "PASS",
                "transcript": {
                    "path": relative(program_log_path),
                    "sha256": sha256_file(program_log_path),
                },
                "result": "J-Link loadfile completed with Program & Verify and O.K.",
            },
            "flash_readback": {
                "status": "PASS",
                "transcript": {
                    "path": relative(compare_log_path),
                    "sha256": sha256_file(compare_log_path),
                },
                "result": "GDB compare-sections matched every loadable ELF section",
                "matched_sections": matched_sections,
            },
            "evidence_boundary": {
                "statement": (
                    "This evidence proves the named ELF was programmed and independently "
                    "read back from the named target; it does not prove P3B load qualification."
                ),
                "pending": pending,
            },
        }
        temporary_evidence.write_bytes(normalized_json(evidence))
        temporary_package.replace(package_path)
        temporary_evidence.replace(evidence_path)
    finally:
        temporary_package.unlink(missing_ok=True)
        temporary_evidence.unlink(missing_ok=True)
    print(
        f"PASS package={evidence['package']['sha256']} "
        f"elf={firmware['demo.elf']['sha256']} source={source_commit} sdk={sdk_commit}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
