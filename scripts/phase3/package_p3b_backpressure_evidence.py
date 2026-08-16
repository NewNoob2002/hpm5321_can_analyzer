#!/usr/bin/env python3
"""Package immutable P3B CAN-load USB backpressure evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = (
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
)
RUN_FILES = (
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "data_loss.csv",
    "events.csv",
    "frames.csv",
    "capture-console.log",
    "backpressure-control.log",
    "backpressure-reconciliation.json",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def normalized_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


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
        path.parent.resolve(strict=True).relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError):
        fail(f"invalid {label}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        fail(f"{label} must be a regular file or absent")
    return path


def regular_file(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError):
        fail(f"missing or invalid {label}: {path}")
    if path.is_symlink() or not resolved.is_file():
        fail(f"{label} must be a regular repository file")
    return resolved


def json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} root must be an object")
    return value


def parse_control(data: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if "=" not in line:
            fail(f"invalid backpressure control line {line_number}")
        name, value = line.split("=", 1)
        if not name or name in values:
            fail(f"invalid backpressure control key: {name}")
        values[name] = value
    required = {
        "pid",
        "measurement_detected",
        "measurement_detected_utc",
        "measurement_detected_monotonic_raw_ns",
        "sigstop_utc",
        "sigstop_after_monotonic_raw_ns",
        "sigcont_utc",
        "sigcont_before_monotonic_raw_ns",
        "pause_duration_ns",
        "pause_duration_seconds",
        "process_returncode",
    }
    if not required.issubset(values):
        fail("backpressure control log is missing required fields")
    return values


def command_output(command: list[str], label: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"unable to read {label}: {result.stderr.strip()}")
    return result.stdout.strip()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def file_reference(data: bytes) -> dict[str, Any]:
    return {"sha256": sha256_bytes(data), "size": len(data)}


def write_package(path: Path, data: dict[str, bytes]) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.comment = b""
            for name in PACKAGE_MEMBERS:
                archive.writestr(zip_info(name), data[name])
        temporary.replace(path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_bytes(normalized_json(value))
        temporary.replace(path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_hotplug(raw: dict[str, Any], source_path: Path) -> dict[str, Any]:
    required = raw.get("required_cycles")
    completed = raw.get("completed_cycles")
    if (
        raw.get("status") != "PASS"
        or raw.get("disconnect_method") != "physical-cable"
        or not isinstance(required, int)
        or required <= 0
        or completed != required
    ):
        fail("physical USB hotplug evidence is not a completed PASS")
    normalized = dict(raw)
    boundary = dict(normalized.get("evidence_boundary", {}))
    cycle_label = "cycle" if required == 1 else "cycles"
    if normalized.get("smoke_kind") == "protocol":
        covered = (
            f"{required} physical disconnect/reconnect {cycle_label}, udev node "
            "access, and a successful UCAN HELLO/device-info/capabilities/"
            "diagnostics transaction after every cycle"
        )
    else:
        covered = (
            f"{required} physical disconnect/reconnect {cycle_label}, udev node "
            "access, and an exact 1 MiB recovery echo after every cycle"
        )
    boundary["covered"] = covered
    normalized["evidence_boundary"] = boundary
    normalized["normalization"] = {
        "source_artifact": source_path.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(source_path),
        "correction": (
            "Replaced the collector's stale hard-coded 100-cycle scope text with "
            "the recorded required/completed cycle count; measurements were not altered."
        ),
    }
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=ROOT
        / "artifacts/hil-2026-08-15/T-CAN-1M-BACKPRESSURE-15S-RECON-120322",
    )
    parser.add_argument(
        "--capture-source",
        type=Path,
        default=ROOT / "host/crates/core/examples/can_hil_capture.rs",
    )
    parser.add_argument(
        "--capture-binary",
        type=Path,
        default=ROOT / "host/target/release/examples/can_hil_capture",
    )
    parser.add_argument(
        "--reconciler",
        type=Path,
        default=ROOT / "scripts/phase3/reconcile_p3b_backpressure.py",
    )
    parser.add_argument(
        "--firmware-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json",
    )
    parser.add_argument(
        "--hotplug-artifact",
        type=Path,
        default=ROOT
        / "artifacts/hil-2026-08-15/P3B-PHYSICAL-USB-HOTPLUG-1CYCLE.json",
    )
    parser.add_argument(
        "--package",
        default="docs/evidence/phase3/P3B-HIL-backpressure-2026-08-15.zip",
    )
    parser.add_argument(
        "--evidence",
        default="docs/evidence/phase3/P3B-HIL-backpressure-evidence-2026-08-15.json",
    )
    parser.add_argument(
        "--hotplug-evidence",
        default="docs/evidence/phase3/P3B-PHYSICAL-USB-HOTPLUG-1CYCLE-2026-08-15.json",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    try:
        run_dir.relative_to(ROOT.resolve())
    except ValueError:
        fail("run directory must be inside the repository")
    files = {
        name: regular_file(run_dir / name, f"backpressure {name}").read_bytes()
        for name in RUN_FILES
    }
    capture_source = regular_file(args.capture_source, "capture source")
    capture_binary = regular_file(args.capture_binary, "capture binary")
    reconciler = regular_file(args.reconciler, "backpressure reconciler")
    firmware_evidence = regular_file(args.firmware_evidence, "firmware evidence")
    hotplug_artifact = regular_file(args.hotplug_artifact, "hotplug artifact")
    package_path = repository_output(args.package, "backpressure package")
    evidence_path = repository_output(args.evidence, "backpressure evidence")
    hotplug_path = repository_output(args.hotplug_evidence, "hotplug evidence")

    summary = json_object(files["summary.json"], "backpressure summary")
    reconciliation = json_object(
        files["backpressure-reconciliation.json"], "backpressure reconciliation"
    )
    control = parse_control(files["backpressure-control.log"])
    if summary.get("warmup_seconds") != 10 or summary.get("duration_seconds") != 60:
        fail("backpressure run must use the frozen 10+60 second profile")
    if summary.get("device_drop_total") != 0:
        fail("backpressure run reports device drops")
    if summary.get("measurement_queue_drops") != 0:
        fail("backpressure run reports queue drops")
    if summary.get("measurement_ring_drops") != 0:
        fail("backpressure run reports ring drops")
    if summary.get("flow_control_events", 0) <= 0:
        fail("backpressure run must record FLOW_CONTROL events")
    if control["measurement_detected"] != "true":
        fail("measurement window was not detected")
    pause_ns = int(control["pause_duration_ns"])
    if not 14_500_000_000 <= pause_ns <= 15_500_000_000:
        fail("backpressure pause must be approximately 15 seconds")
    if int(control["process_returncode"]) != 1:
        fail("backpressure collector must fail the frozen zero-loss acceptance")
    expected_reconciliation = {
        "status": "PARTIAL",
        "usb_backpressure_recovery": "PASS",
        "event_sequence_reconciliation": "PASS",
        "channel_sequence_reconciliation": "PARTIAL",
        "errors": [],
    }
    for name, expected in expected_reconciliation.items():
        if reconciliation.get(name) != expected:
            fail(f"unexpected backpressure reconciliation: {name}")
    if reconciliation.get("observed_event_missing_count") != reconciliation.get(
        "declared_event_loss_count"
    ):
        fail("EVENT-domain missing/declaration counts do not reconcile")
    if reconciliation.get("observed_event_missing_count") != summary.get(
        "event_missing_sequences"
    ):
        fail("summary EVENT-domain gap count mismatch")
    if reconciliation.get("flow_control_event_count") != summary.get(
        "flow_control_events"
    ):
        fail("summary FLOW_CONTROL count mismatch")
    if reconciliation.get("channel_missing_records") != summary.get(
        "forward_missing_records"
    ):
        fail("summary channel gap count mismatch")

    head = command_output(["git", "rev-parse", "HEAD"], "source commit")
    source_dirty = bool(command_output(["git", "status", "--porcelain"], "source status"))
    compiler = command_output(["rustc", "--version"], "Rust compiler")
    capture_source_bytes = capture_source.read_bytes()
    capture_binary_bytes = capture_binary.read_bytes()
    reconciler_bytes = reconciler.read_bytes()
    firmware_sha256 = sha256_file(firmware_evidence)
    file_references = {name: file_reference(data) for name, data in files.items()}
    manifest = {
        "schema": 1,
        "evidence_id": "P3B-HIL-backpressure-2026-08-15",
        "phase": "P3B",
        "test": "CAN-load USB backpressure and EVENT-domain drop reconciliation",
        "command": (
            "host/target/release/examples/can_hil_capture 10 60 "
            "artifacts/hil-2026-08-15/T-CAN-1M-BACKPRESSURE-15S-RECON-120322"
        ),
        "injection": {
            "method": "SIGSTOP/SIGCONT on host collector",
            "measurement_offset_seconds": 10,
            "pause_duration_ns": pause_ns,
            "pause_duration_seconds": float(control["pause_duration_seconds"]),
        },
        "capture_tool": {
            "source_commit": head,
            "source_dirty": source_dirty,
            "source_member": "capture/can_hil_capture.rs",
            "source_sha256": sha256_bytes(capture_source_bytes),
            "binary_member": "capture/can_hil_capture",
            "binary_sha256": sha256_bytes(capture_binary_bytes),
            "binary_size": len(capture_binary_bytes),
            "compiler": compiler,
        },
        "reconciliation_tool": {
            "member": "reconcile/reconcile_p3b_backpressure.py",
            "sha256": sha256_bytes(reconciler_bytes),
        },
        "firmware_evidence": {
            "path": firmware_evidence.relative_to(ROOT).as_posix(),
            "sha256": firmware_sha256,
        },
        "files": file_references,
        "control": {
            name: control[name]
            for name in (
                "pid",
                "measurement_detected_utc",
                "measurement_detected_monotonic_raw_ns",
                "sigstop_utc",
                "sigstop_after_monotonic_raw_ns",
                "sigcont_utc",
                "sigcont_before_monotonic_raw_ns",
                "pause_duration_ns",
                "pause_duration_seconds",
                "process_returncode",
            )
        },
        "acceptance_observed": {
            name: summary.get(name)
            for name in (
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
        },
        "reconciliation": reconciliation,
        "result": "PARTIAL_CHANNEL_ATTRIBUTION",
    }
    package_data = {
        "run-manifest.json": normalized_json(manifest),
        **files,
        "capture/can_hil_capture.rs": capture_source_bytes,
        "capture/can_hil_capture": capture_binary_bytes,
        "reconcile/reconcile_p3b_backpressure.py": reconciler_bytes,
    }
    write_package(package_path, package_data)
    evidence = {
        "schema": 1,
        "evidence_id": "P3B-HIL-backpressure-evidence-2026-08-15",
        "phase": "P3B",
        "status": "PARTIAL",
        "package": {
            "path": package_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(package_path),
            "size": package_path.stat().st_size,
            "members": list(PACKAGE_MEMBERS),
            "run_manifest_sha256": sha256_bytes(package_data["run-manifest.json"]),
        },
        "outcomes": {
            "usb_backpressure_recovery": "PASS",
            "event_domain_state_drop_reconciliation": "PASS",
            "channel_sequence_reconciliation": "PARTIAL",
        },
        "evidence_boundary": {
            "statement": (
                "The host collector was paused for approximately 15 seconds under "
                "the active 1 Mbit/s >=6000 frame/s source. USB/protocol delivery "
                "recovered and every missing EVENT sequence was exactly declared by "
                "EVENT-domain DATA_LOSS."
            ),
            "limitations": reconciliation["limitations"],
        },
    }
    write_json(evidence_path, evidence)

    hotplug_raw = json_object(hotplug_artifact.read_bytes(), "hotplug artifact")
    write_json(hotplug_path, normalize_hotplug(hotplug_raw, hotplug_artifact))
    print(
        "PASS backpressure=PARTIAL recovery=PASS event_reconciliation=PASS "
        f"package={evidence['package']['sha256']} hotplug=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
