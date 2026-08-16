#!/usr/bin/env python3
"""Archive the P3B no-traffic preflight and publish the current gate status."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PREFLIGHT_MEMBERS = (
    "summary.json",
    "diagnostics.csv",
    "frames.csv",
    "pings.csv",
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
    path = ROOT / safe_relative_path(relative, label)
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


def validate_firmware_evidence(manifest_path: Path) -> list[str]:
    module_path = Path(__file__).with_name("validate_hil_firmware_evidence.py")
    spec = importlib.util.spec_from_file_location(
        "p3b_packager_firmware_evidence_validator", module_path
    )
    if spec is None or spec.loader is None:
        return ["unable to load firmware evidence validator"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate(ROOT, manifest_path.relative_to(ROOT.resolve()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight-dir",
        type=Path,
        default=ROOT / "artifacts/hil-2026-08-14/T-CAN-1M-PREFLIGHT-5S",
    )
    parser.add_argument(
        "--firmware-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json",
    )
    parser.add_argument(
        "--backpressure-log",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-USB-backpressure-no-can-load-2026-08-14.txt",
    )
    parser.add_argument(
        "--ping-soak-log",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-USB-ping-soak-no-can-load-2026-08-14.txt",
    )
    parser.add_argument(
        "--inventory-log",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-external-hardware-inventory-2026-08-14.txt",
    )
    parser.add_argument(
        "--package",
        default="docs/evidence/phase3/P3B-HIL-preflight-no-traffic-2026-08-14.zip",
    )
    parser.add_argument(
        "--status",
        default="docs/evidence/phase3/P3B-HIL-execution-status-2026-08-14.json",
    )
    args = parser.parse_args()

    package_path = repository_output(args.package, "preflight package output")
    status_path = repository_output(args.status, "execution status output")
    if package_path == status_path:
        fail("preflight package and status outputs must be distinct")
    firmware_evidence_path = regular_file(args.firmware_evidence, "firmware evidence")
    backpressure_path = regular_file(args.backpressure_log, "backpressure transcript")
    ping_soak_path = regular_file(args.ping_soak_log, "ping soak transcript")
    inventory_path = regular_file(args.inventory_log, "hardware inventory transcript")
    root_resolved = ROOT.resolve()

    def relative(path: Path) -> str:
        return path.relative_to(root_resolved).as_posix()

    for path in (
        package_path,
        status_path,
        firmware_evidence_path,
        backpressure_path,
        ping_soak_path,
        inventory_path,
    ):
        relative(path)

    preflight_bytes: dict[str, bytes] = {}
    for name in PREFLIGHT_MEMBERS:
        preflight_bytes[name] = regular_file(
            args.preflight_dir / name, f"preflight {name}"
        ).read_bytes()
    try:
        summary = json.loads(preflight_bytes["summary.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid preflight summary: {exc}")
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
            fail(f"unexpected no-traffic preflight summary: {name}")

    firmware_evidence = json_object(firmware_evidence_path, "firmware evidence")
    firmware_errors = validate_firmware_evidence(firmware_evidence_path)
    if firmware_errors:
        fail("firmware evidence validation failed: " + "; ".join(firmware_errors))
    if (
        firmware_evidence.get("status") != "PASS"
        or firmware_evidence.get("qualification_status") != "PARTIAL"
        or firmware_evidence.get("p4e_gate") != "BLOCKED"
    ):
        fail("firmware evidence boundary is invalid")

    backpressure_text = backpressure_path.read_text(encoding="utf-8")
    ping_soak_text = ping_soak_path.read_text(encoding="utf-8")
    inventory_text = inventory_path.read_text(encoding="utf-8")
    if "PASS backpressure_pause_ms=15000" not in backpressure_text:
        fail("no-load backpressure transcript is not PASS")
    if "PASS ping_soak elapsed_s=" not in ping_soak_text or "dropped=0" not in ping_soak_text:
        fail("no-load ping soak transcript is not PASS")
    if "DETECTED_SOCKETCAN_INTERFACES none" not in inventory_text:
        fail("hardware inventory does not prove SocketCAN absence")
    if (
        "OBSERVATION no active external CAN traffic was observed by the 5-second "
        "frozen-profile preflight"
    ) not in inventory_text:
        fail("hardware inventory is missing the no-traffic observation")
    captured_at = marker(inventory_text, "P3B_EXTERNAL_HARDWARE_INVENTORY_DATE_UTC")

    with tempfile.NamedTemporaryFile(
        dir=package_path.parent,
        prefix=f".{package_path.name}.",
        delete=False,
    ) as stream:
        temporary_package = Path(stream.name)
    with tempfile.NamedTemporaryFile(
        dir=status_path.parent,
        prefix=f".{status_path.name}.",
        delete=False,
    ) as stream:
        temporary_status = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary_package, "w") as archive:
            archive.comment = b""
            for name in PREFLIGHT_MEMBERS:
                archive.writestr(zip_info(name), preflight_bytes[name])

        boundary = firmware_evidence.get("evidence_boundary")
        pending = boundary.get("pending") if isinstance(boundary, dict) else None
        if not isinstance(pending, list) or not all(
            isinstance(item, str) for item in pending
        ):
            fail("firmware evidence requires a string pending list")
        status = {
        "schema": 1,
        "evidence_id": "P3B-HIL-execution-status-2026-08-14",
        "phase": "P3B",
        "captured_at_utc": captured_at,
        "qualification_status": "PARTIAL",
        "p4e_gate": "BLOCKED",
        "frozen_profile": {
            "required_command": (
                "cd host && cargo run -p hpm-usb-can-core --release "
                "--example can_hil_capture -- 60 1800 "
                "../artifacts/hil-2026-08-14/T-CAN-1M-30MIN"
            ),
            "acceptance": {
                "minimum_frames_per_second": 6000,
                "event_sequence_gaps": 0,
                "channel_sequence_gaps": 0,
                "queue_drops": 0,
                "ring_drops": 0,
                "device_drops": 0,
                "latency_p95_ns_max": 5_000_000,
                "clock_fit_residual_p95_ns_max": 1_000_000,
            },
            "long_run_started": False,
            "blocked_reason": (
                "The 5-second preflight observed zero CAN frames; starting the "
                "1800-second qualification run would not exercise the frozen profile."
            ),
        },
        "firmware_evidence": {
            "path": relative(firmware_evidence_path),
            "sha256": sha256_file(firmware_evidence_path),
        },
        "preflight": {
            "command": (
                "cd host && cargo run -p hpm-usb-can-core --release "
                "--example can_hil_capture -- 1 5 "
                "../artifacts/hil-2026-08-14/T-CAN-1M-PREFLIGHT-5S"
            ),
            "result": "BLOCKED_NO_EXTERNAL_CAN_TRAFFIC",
            "package": {
                "path": relative(package_path),
                "sha256": sha256_file(temporary_package),
                "size": temporary_package.stat().st_size,
                "members": list(PREFLIGHT_MEMBERS),
            },
            "summary_sha256": sha256_bytes(preflight_bytes["summary.json"]),
            "observed_frames": summary["frames"],
            "observed_frames_per_second": summary["frames_per_second"],
        },
        "no_can_load_baselines": {
            "usb_backpressure": {
                "status": "PASS",
                "scope": "15-second host read pause without CAN traffic",
                "transcript": {
                    "path": relative(backpressure_path),
                    "sha256": sha256_file(backpressure_path),
                },
            },
            "usb_ping_soak": {
                "status": "PASS",
                "scope": "60-second protocol ping soak without CAN traffic",
                "transcript": {
                    "path": relative(ping_soak_path),
                    "sha256": sha256_file(ping_soak_path),
                },
            },
        },
        "hardware_inventory": {
            "path": relative(inventory_path),
            "sha256": sha256_file(inventory_path),
            "socketcan_interfaces": [],
            "unclassified_serial_nodes": ["/dev/ttyACM0"],
            "independent_analyzer_evidence": None,
        },
        "evidence_boundary": {
            "statement": (
                "No-load USB checks passed, but they do not satisfy CAN-load "
                "backpressure or any external-analyzer acceptance criterion."
            ),
            "pending": pending,
        },
        }
        temporary_status.write_bytes(normalized_json(status))
        temporary_package.replace(package_path)
        temporary_status.replace(status_path)
    finally:
        temporary_package.unlink(missing_ok=True)
        temporary_status.unlink(missing_ok=True)
    print(
        f"PASS status=PARTIAL package={status['preflight']['package']['sha256']} "
        "reason=BLOCKED_NO_EXTERNAL_CAN_TRAFFIC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
