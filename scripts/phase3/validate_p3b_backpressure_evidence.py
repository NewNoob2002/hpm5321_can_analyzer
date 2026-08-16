#!/usr/bin/env python3
"""Validate immutable P3B CAN-load USB backpressure evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.phase3.external_artifact_index import validate_detached_reference
except ModuleNotFoundError:  # Direct execution adds scripts/phase3, not repo root.
    from external_artifact_index import validate_detached_reference


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = Path(
    "docs/evidence/phase3/P3B-HIL-backpressure-evidence-2026-08-15.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = [
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "data_loss.csv",
    "events.csv",
    "frames.csv",
    "capture-console.log",
    "backpressure-control.log",
    "backpressure-reconciliation.json",
    "capture/can_hil_capture.rs",
    "capture/can_hil_capture",
    "reconcile/reconcile_p3b_backpressure.py",
]
RUN_FILES = PACKAGE_MEMBERS[1:10]


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


def json_object(data: bytes, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def parse_control(data: bytes, errors: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        errors.append(f"invalid backpressure control log: {exc}")
        return values
    for line_number, line in enumerate(lines, start=1):
        if "=" not in line:
            errors.append(f"invalid backpressure control line {line_number}")
            continue
        name, value = line.split("=", 1)
        if not name or name in values:
            errors.append(f"invalid backpressure control key: {name}")
            continue
        values[name] = value
    return values


def load_reconciler():
    path = ROOT / "scripts/phase3/reconcile_p3b_backpressure.py"
    spec = importlib.util.spec_from_file_location("p3b_backpressure_reconciler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(
    root: Path, evidence_relative: Path = DEFAULT_EVIDENCE
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    evidence_path = repository_file(
        root, evidence_relative.as_posix(), "backpressure evidence", errors
    )
    if evidence_path is None:
        return errors
    evidence = json_object(
        evidence_path.read_bytes(), "backpressure evidence", errors
    )
    if evidence.get("schema") != 1:
        errors.append("unsupported backpressure evidence schema")
    if evidence.get("evidence_id") != "P3B-HIL-backpressure-evidence-2026-08-15":
        errors.append("unexpected backpressure evidence ID")
    if evidence.get("phase") != "P3B":
        errors.append("backpressure evidence phase must be P3B")
    if evidence.get("status") != "PARTIAL":
        errors.append("backpressure evidence must remain PARTIAL")
    expected_outcomes = {
        "usb_backpressure_recovery": "PASS",
        "event_domain_state_drop_reconciliation": "PASS",
        "channel_sequence_reconciliation": "PARTIAL",
    }
    if evidence.get("outcomes") != expected_outcomes:
        errors.append("backpressure evidence outcomes mismatch")

    package = evidence.get("package")
    if not isinstance(package, dict):
        errors.append("backpressure package reference is missing")
        return errors
    relative = safe_relative_path(package.get("path"), "backpressure package", errors)
    if relative is None:
        return errors
    candidate = root / relative
    if not candidate.exists():
        artifact = validate_detached_reference(root, package, errors)
        expected_excerpt = {
            "source_evidence": DEFAULT_EVIDENCE.as_posix(),
            "result": "PARTIAL_CHANNEL_ATTRIBUTION",
            "run_manifest_sha256": package.get("run_manifest_sha256"),
            "pause_duration_ns": 15004321839,
            "frames": 271293,
            "event_missing_sequences": 12913,
            "flow_control_events": 3,
            "host_acceptance": False,
            "usb_backpressure_recovery": "PASS",
            "event_sequence_reconciliation": "PASS",
            "channel_sequence_reconciliation": "PARTIAL",
        }
        if artifact is not None and artifact.get("key_excerpt") != expected_excerpt:
            errors.append("backpressure detached key excerpt mismatch")
        return errors
    package_path = repository_file(root, relative, "backpressure package", errors)
    if package_path is None:
        return errors
    if package.get("size") != package_path.stat().st_size:
        errors.append("backpressure package size mismatch")
    if package.get("sha256") != sha256_file(package_path):
        errors.append("backpressure package SHA-256 mismatch")
    if package.get("members") != PACKAGE_MEMBERS:
        errors.append("backpressure package member reference mismatch")

    members: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append("backpressure package comment is not allowed")
            if archive.namelist() != PACKAGE_MEMBERS:
                errors.append("backpressure package member list mismatch")
            for info, expected in zip(
                archive.infolist(), PACKAGE_MEMBERS, strict=False
            ):
                safe_relative_path(info.filename, "backpressure package member", errors)
                if info.filename != expected:
                    errors.append("backpressure package member list mismatch")
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
                    errors.append(
                        f"backpressure package member metadata mismatch: {info.filename}"
                    )
                if not 0 < info.file_size <= 32 * 1024 * 1024:
                    errors.append(
                        f"backpressure package member size is invalid: {info.filename}"
                    )
            for name in PACKAGE_MEMBERS:
                members[name] = archive.read(name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid backpressure package: {exc}")
        return errors

    if package.get("run_manifest_sha256") != sha256_bytes(
        members["run-manifest.json"]
    ):
        errors.append("backpressure run manifest SHA-256 mismatch")
    manifest = json_object(
        members["run-manifest.json"], "backpressure run manifest", errors
    )
    summary = json_object(members["summary.json"], "backpressure summary", errors)
    recorded = json_object(
        members["backpressure-reconciliation.json"],
        "backpressure reconciliation",
        errors,
    )
    if manifest.get("schema") != 1:
        errors.append("unsupported backpressure run manifest schema")
    if manifest.get("evidence_id") != "P3B-HIL-backpressure-2026-08-15":
        errors.append("unexpected backpressure run evidence ID")
    if manifest.get("phase") != "P3B":
        errors.append("backpressure run phase must be P3B")
    if manifest.get("result") != "PARTIAL_CHANNEL_ATTRIBUTION":
        errors.append("backpressure run result mismatch")

    references = manifest.get("files")
    if not isinstance(references, dict):
        errors.append("backpressure run file references are missing")
        references = {}
    for name in RUN_FILES:
        if references.get(name) != {
            "sha256": sha256_bytes(members[name]),
            "size": len(members[name]),
        }:
            errors.append(f"backpressure member reference mismatch: {name}")

    capture = manifest.get("capture_tool")
    if not isinstance(capture, dict):
        errors.append("backpressure capture tool evidence is missing")
        capture = {}
    expected_capture_members = {
        "source_member": "capture/can_hil_capture.rs",
        "source_sha256": sha256_bytes(members["capture/can_hil_capture.rs"]),
        "binary_member": "capture/can_hil_capture",
        "binary_sha256": sha256_bytes(members["capture/can_hil_capture"]),
        "binary_size": len(members["capture/can_hil_capture"]),
    }
    for name, expected in expected_capture_members.items():
        if capture.get(name) != expected:
            errors.append(f"backpressure capture tool mismatch: {name}")
    if not isinstance(capture.get("source_commit"), str) or len(
        capture["source_commit"]
    ) != 40:
        errors.append("backpressure source commit is invalid")
    if capture.get("source_dirty") is not True:
        errors.append("backpressure source dirty state mismatch")
    if not isinstance(capture.get("compiler"), str) or not capture["compiler"]:
        errors.append("backpressure compiler evidence is missing")

    tool = manifest.get("reconciliation_tool")
    current_reconciler = root / "scripts/phase3/reconcile_p3b_backpressure.py"
    archived_reconciler = members["reconcile/reconcile_p3b_backpressure.py"]
    if tool != {
        "member": "reconcile/reconcile_p3b_backpressure.py",
        "sha256": sha256_bytes(archived_reconciler),
    }:
        errors.append("backpressure reconciliation tool evidence mismatch")
    if sha256_file(current_reconciler) != sha256_bytes(archived_reconciler):
        errors.append("versioned backpressure reconciler differs from archived tool")

    control = parse_control(members["backpressure-control.log"], errors)
    if control.get("measurement_detected") != "true":
        errors.append("backpressure measurement window was not detected")
    try:
        pause_ns = int(control.get("pause_duration_ns", ""))
    except ValueError:
        pause_ns = 0
        errors.append("backpressure pause duration is invalid")
    if not 14_500_000_000 <= pause_ns <= 15_500_000_000:
        errors.append("backpressure pause was not approximately 15 seconds")
    if control.get("process_returncode") != "1":
        errors.append("backpressure collector return code mismatch")
    injection = manifest.get("injection")
    if not isinstance(injection, dict) or injection.get("pause_duration_ns") != pause_ns:
        errors.append("backpressure injection metadata mismatch")

    observed_names = (
        "warmup_seconds",
        "duration_seconds",
        "frames",
        "frames_per_second",
        "event_gaps",
        "event_missing_sequences",
        "flow_control_events",
        "channel_gaps",
        "forward_missing_records",
        "device_drop_total",
        "measurement_queue_drops",
        "measurement_ring_drops",
        "data_loss_events",
        "data_loss_dropped",
        "latency_ns_p95",
        "fit_residual_ns_p95",
        "host_acceptance",
    )
    expected_observed = {name: summary.get(name) for name in observed_names}
    if manifest.get("acceptance_observed") != expected_observed:
        errors.append("backpressure observed acceptance mismatch")
    if summary.get("warmup_seconds") != 10 or summary.get("duration_seconds") != 60:
        errors.append("backpressure profile mismatch")
    for name in (
        "device_drop_total",
        "measurement_queue_drops",
        "measurement_ring_drops",
    ):
        if summary.get(name) != 0:
            errors.append(f"backpressure run reports unexpected {name}")
    if summary.get("flow_control_events", 0) <= 0:
        errors.append("backpressure run did not record FLOW_CONTROL")
    if summary.get("host_acceptance") is not False:
        errors.append("backpressure run must fail frozen zero-loss acceptance")

    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        for name in ("summary.json", "events.csv", "data_loss.csv", "frames.csv"):
            (run_dir / name).write_bytes(members[name])
        recomputed = load_reconciler().reconcile(run_dir)
    if recomputed != recorded:
        errors.append("backpressure reconciliation replay mismatch")
    if manifest.get("reconciliation") != recorded:
        errors.append("backpressure manifest reconciliation mismatch")
    expected_reconciliation = {
        "status": "PARTIAL",
        "usb_backpressure_recovery": "PASS",
        "event_sequence_reconciliation": "PASS",
        "channel_sequence_reconciliation": "PARTIAL",
        "errors": [],
    }
    for name, expected in expected_reconciliation.items():
        if recorded.get(name) != expected:
            errors.append(f"backpressure reconciliation mismatch: {name}")
    if recorded.get("observed_event_missing_count") != recorded.get(
        "declared_event_loss_count"
    ):
        errors.append("EVENT-domain drop counts do not reconcile")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    errors = validate(args.root, args.evidence)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS USB backpressure recovery and EVENT-domain reconciliation; "
        "channel attribution remains PARTIAL"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
