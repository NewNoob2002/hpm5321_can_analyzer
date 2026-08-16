#!/usr/bin/env python3
"""Validate the current P3B execution boundary and no-traffic preflight."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(
    "docs/evidence/phase3/P3B-HIL-execution-status-2026-08-14.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PREFLIGHT_MEMBERS = (
    "summary.json",
    "diagnostics.csv",
    "frames.csv",
    "pings.csv",
)
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024


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


def read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return None
    return value


def validate_zip_info(info: zipfile.ZipInfo, expected: str, errors: list[str]) -> None:
    safe_relative_path(info.filename, "preflight package member", errors)
    if info.filename != expected:
        errors.append("preflight package member list mismatch")
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
        errors.append(f"preflight package member metadata mismatch: {info.filename}")


def validate_firmware_evidence(
    root: Path, manifest_relative: Path
) -> list[str]:
    module_path = Path(__file__).with_name("validate_hil_firmware_evidence.py")
    spec = importlib.util.spec_from_file_location(
        "p3b_nested_firmware_evidence_validator", module_path
    )
    if spec is None or spec.loader is None:
        return ["unable to load firmware evidence validator"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate(root, manifest_relative)


def validate(root: Path, manifest_relative: Path = DEFAULT_MANIFEST) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    manifest_path = repository_file(root, manifest_relative.as_posix(), "status manifest", errors)
    if manifest_path is None:
        return errors
    status = read_json(manifest_path, "status manifest", errors)
    if status is None:
        return errors

    if status.get("schema") != 1:
        errors.append("unsupported status manifest schema")
    if status.get("evidence_id") != "P3B-HIL-execution-status-2026-08-14":
        errors.append("unexpected status evidence ID")
    if status.get("phase") != "P3B":
        errors.append("status phase must be P3B")
    if status.get("qualification_status") != "PARTIAL":
        errors.append("P3B qualification must remain PARTIAL")
    if status.get("p4e_gate") != "BLOCKED":
        errors.append("P4E gate must remain BLOCKED")

    frozen = status.get("frozen_profile")
    if not isinstance(frozen, dict):
        errors.append("status requires frozen profile")
        frozen = {}
    required_command = frozen.get("required_command")
    if not isinstance(required_command, str):
        errors.append("frozen profile command must be a string")
        required_command = ""
    for token in ("can_hil_capture -- 60 1800", "T-CAN-1M-30MIN"):
        if token not in required_command:
            errors.append(f"frozen profile command is missing {token}")
    if frozen.get("long_run_started") is not False:
        errors.append("status must record that the long run was not started")
    blocked_reason = frozen.get("blocked_reason")
    if not isinstance(blocked_reason, str) or "zero CAN frames" not in blocked_reason:
        errors.append("status blocked reason must identify zero CAN frames")
    expected_acceptance = {
        "minimum_frames_per_second": 6000,
        "event_sequence_gaps": 0,
        "channel_sequence_gaps": 0,
        "queue_drops": 0,
        "ring_drops": 0,
        "device_drops": 0,
        "latency_p95_ns_max": 5_000_000,
        "clock_fit_residual_p95_ns_max": 1_000_000,
    }
    if frozen.get("acceptance") != expected_acceptance:
        errors.append("frozen profile acceptance mismatch")

    firmware = status.get("firmware_evidence")
    if not isinstance(firmware, dict):
        errors.append("status requires firmware evidence")
        firmware = {}
    firmware_path = repository_file(
        root, firmware.get("path"), "firmware evidence", errors
    )
    if firmware_path is not None:
        if firmware.get("sha256") != sha256_file(firmware_path):
            errors.append("firmware evidence SHA-256 mismatch")
        for error in validate_firmware_evidence(
            root, firmware_path.relative_to(root)
        ):
            errors.append(f"firmware evidence: {error}")

    preflight = status.get("preflight")
    if not isinstance(preflight, dict):
        errors.append("status requires preflight")
        return errors
    if preflight.get("result") != "BLOCKED_NO_EXTERNAL_CAN_TRAFFIC":
        errors.append("preflight result mismatch")
    if preflight.get("observed_frames") != 0 or preflight.get(
        "observed_frames_per_second"
    ) != 0.0:
        errors.append("preflight must record zero observed traffic")
    package = preflight.get("package")
    if not isinstance(package, dict):
        errors.append("preflight requires package")
        return errors
    package_path = repository_file(root, package.get("path"), "preflight package", errors)
    if package_path is None:
        return errors
    if not 0 < package_path.stat().st_size <= MAX_PACKAGE_BYTES:
        errors.append("preflight package size is invalid")
    if package.get("size") != package_path.stat().st_size:
        errors.append("preflight package size mismatch")
    if package.get("sha256") != sha256_file(package_path):
        errors.append("preflight package SHA-256 mismatch")
    if package.get("members") != list(PREFLIGHT_MEMBERS):
        errors.append("status preflight member list mismatch")

    members: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append("preflight package archive comment is not allowed")
            if archive.namelist() != list(PREFLIGHT_MEMBERS):
                errors.append("preflight package member list mismatch")
            infos = archive.infolist()
            for info, expected in zip(infos, PREFLIGHT_MEMBERS, strict=False):
                validate_zip_info(info, expected, errors)
                if not 0 < info.file_size <= MAX_MEMBER_BYTES:
                    errors.append(f"preflight package member size is invalid: {info.filename}")
            for name in PREFLIGHT_MEMBERS:
                members[name] = archive.read(name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid preflight package: {exc}")
        return errors
    if preflight.get("summary_sha256") != sha256_bytes(members["summary.json"]):
        errors.append("preflight summary SHA-256 mismatch")
    try:
        summary = json.loads(members["summary.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid preflight summary: {exc}")
        summary = {}
    if not isinstance(summary, dict):
        errors.append("preflight summary root must be an object")
        summary = {}
    expected_summary = {
        "status": "FAIL",
        "warmup_seconds": 1,
        "duration_seconds": 5,
        "frames": 0,
        "frames_per_second": 0.0,
        "host_acceptance": False,
        "external_analyzer_reconciliation": "PENDING",
        "tx_armed_before_capture": False,
        "tx_operations_issued": 0,
    }
    for name, expected in expected_summary.items():
        if summary.get(name) != expected:
            errors.append(f"preflight summary mismatch: {name}")

    baselines = status.get("no_can_load_baselines")
    if not isinstance(baselines, dict):
        errors.append("status requires no-load baselines")
        baselines = {}
    for name, token in (
        ("usb_backpressure", "PASS backpressure_pause_ms=15000"),
        ("usb_ping_soak", "PASS ping_soak elapsed_s="),
    ):
        baseline = baselines.get(name)
        if not isinstance(baseline, dict) or baseline.get("status") != "PASS":
            errors.append(f"no-load baseline is not PASS: {name}")
            continue
        transcript = baseline.get("transcript")
        if not isinstance(transcript, dict):
            errors.append(f"no-load baseline transcript is missing: {name}")
            continue
        transcript_path = repository_file(
            root, transcript.get("path"), f"{name} transcript", errors
        )
        if transcript_path is None:
            continue
        if transcript.get("sha256") != sha256_file(transcript_path):
            errors.append(f"no-load baseline transcript SHA-256 mismatch: {name}")
        if token not in transcript_path.read_text(encoding="utf-8"):
            errors.append(f"no-load baseline PASS token missing: {name}")

    inventory = status.get("hardware_inventory")
    if not isinstance(inventory, dict):
        errors.append("status requires hardware inventory")
        inventory = {}
    inventory_path = repository_file(
        root, inventory.get("path"), "hardware inventory", errors
    )
    if inventory_path is not None:
        if inventory.get("sha256") != sha256_file(inventory_path):
            errors.append("hardware inventory SHA-256 mismatch")
        inventory_text = inventory_path.read_text(encoding="utf-8")
        if "DETECTED_SOCKETCAN_INTERFACES none" not in inventory_text:
            errors.append("hardware inventory SocketCAN boundary mismatch")
        if "no active external CAN traffic was observed" not in inventory_text:
            errors.append("hardware inventory no-traffic observation missing")
    if inventory.get("socketcan_interfaces") != []:
        errors.append("status must not claim a SocketCAN interface")
    if inventory.get("independent_analyzer_evidence") is not None:
        errors.append("status must not claim independent analyzer evidence")

    boundary = status.get("evidence_boundary")
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
        errors.append("execution evidence boundary pending set mismatch")
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
    print("PASS P3B execution status remains PARTIAL with P4E blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
