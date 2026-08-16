#!/usr/bin/env python3
"""Package immutable P3B CAN-load evidence with compressed raw frame CSVs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FRAME_HEADER = (
    "host_ingest_ns,device_tick,channel_sequence,arbitration_id,flags,dlc,"
    "device_drop_total,event_sequence,payload_hex"
)
DATA_LOSS_HEADER = (
    "host_ingest_ns,device_tick,event_sequence,channel,source,sequence_domain,reason,"
    "config_generation,first_dropped_sequence,last_dropped_sequence,dropped_count"
)
FAILED_LONG_RUN_MEMBERS = (
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "frames.csv",
    "channel-gap-excerpt.csv",
    "jlink-reset.txt",
)
QUALIFIED_LONG_RUN_MEMBERS = (
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "frames.csv",
    "data_loss.csv",
    "capture/capture-tool-anchor.json",
    "capture/can_hil_capture.rs",
    "capture/can_hil_capture",
    "operator-attestation.txt",
)
DIAGNOSTIC_MEMBERS = (
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "frames.csv",
    "data_loss.csv",
    "jlink-reset.txt",
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


def zip_info(name: str, compressed: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def iso_utc_from_ns(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1_000_000_000, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def analyze_frames(path: Path) -> tuple[dict[str, Any], bytes]:
    digest = hashlib.sha256()
    row_count = 0
    previous_sequence = 0
    gap_count = 0
    previous_rows: deque[bytes] = deque(maxlen=3)
    excerpt_rows: list[bytes] = []
    following_rows = 0
    first_values: list[str] | None = None
    last_values: list[str] | None = None

    with path.open("rb") as stream:
        header = stream.readline()
        digest.update(header)
        if header.rstrip(b"\r\n").decode("ascii") != FRAME_HEADER:
            fail(f"unexpected frames.csv header: {path}")
        for raw_line in stream:
            digest.update(raw_line)
            values = next(csv.reader([raw_line.decode("ascii")]))
            if len(values) != 9:
                fail(f"invalid frames.csv row width: {path}")
            row_count += 1
            if first_values is None:
                first_values = values
            last_values = values
            sequence = int(values[2])
            expected = (previous_sequence + 1) & 0xFFFF_FFFF
            if expected == 0:
                expected = 1
            if previous_sequence != 0 and sequence != expected:
                gap_count += 1
                if excerpt_rows:
                    excerpt_rows.append(b"\n")
                excerpt_rows.extend(previous_rows)
                excerpt_rows.append(raw_line)
                following_rows = 3
            elif following_rows:
                excerpt_rows.append(raw_line)
                following_rows -= 1
            previous_rows.append(raw_line)
            previous_sequence = sequence

    if first_values is None or last_values is None:
        fail(f"frames.csv contains no data rows: {path}")
    excerpt = (FRAME_HEADER + "\n").encode() + b"".join(excerpt_rows)
    active_span_seconds = (
        int(last_values[0]) - int(first_values[0])
    ) / 1_000_000_000
    metadata = {
        "archived": True,
        "member": "frames.csv",
        "compression": "zip-deflate",
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
        "row_count": row_count,
        "channel_gap_count": gap_count,
        "first_host_ingest_ns": int(first_values[0]),
        "last_host_ingest_ns": int(last_values[0]),
        "first_device_tick": int(first_values[1]),
        "last_device_tick": int(last_values[1]),
        "first_channel_sequence": int(first_values[2]),
        "last_channel_sequence": int(last_values[2]),
        "measurement_first_frame_utc": iso_utc_from_ns(int(first_values[0])),
        "measurement_last_frame_utc": iso_utc_from_ns(int(last_values[0])),
        "active_frame_span_seconds": active_span_seconds,
        "frames_per_second_over_active_span": (
            (row_count - 1) / active_span_seconds
            if active_span_seconds > 0
            else 0.0
        ),
    }
    return metadata, excerpt


def analyze_measurement_window(
    diagnostics: bytes, frames: dict[str, Any], label: str
) -> dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(diagnostics.decode("ascii"))))
    starts = [row for row in rows if row.get("phase") == "measurement_start"]
    ends = [row for row in rows if row.get("phase") == "measurement_end"]
    if len(starts) != 1 or len(ends) != 1:
        fail(f"{label} diagnostics require one measurement start and end")
    start_host_ns = int(starts[0]["host_poll_ns"])
    end_host_ns = int(ends[0]["host_poll_ns"])
    return {
        "start_host_ns": start_host_ns,
        "end_host_ns": end_host_ns,
        "duration_seconds": (end_host_ns - start_host_ns) / 1_000_000_000,
        "start_device_tick": int(starts[0]["snapshot_tick"]),
        "end_device_tick": int(ends[0]["snapshot_tick"]),
        "first_frame_delay_seconds": (
            frames["first_host_ingest_ns"] - start_host_ns
        )
        / 1_000_000_000,
        "last_frame_offset_from_end_seconds": (
            frames["last_host_ingest_ns"] - end_host_ns
        )
        / 1_000_000_000,
    }


def load_run(
    directory: Path, label: str
) -> tuple[dict[str, Any], dict[str, bytes | Path]]:
    files = {
        name: regular_file(directory / name, f"{label} {name}").read_bytes()
        for name in ("summary.json", "diagnostics.csv", "pings.csv")
    }
    summary = json_object(files["summary.json"], f"{label} summary")
    frames_path = regular_file(directory / "frames.csv", f"{label} frames.csv")
    frames, gap_excerpt = analyze_frames(frames_path)
    if frames["row_count"] != summary.get("frames"):
        fail(f"{label} frame row count does not match summary")
    if frames["channel_gap_count"] != summary.get("channel_gaps"):
        fail(f"{label} channel gap count does not match summary")
    measurement_window = analyze_measurement_window(
        files["diagnostics.csv"], frames, label
    )
    return {
        "summary": summary,
        "frames": frames,
        "measurement_window": measurement_window,
    }, files | {
        "channel-gap-excerpt.csv": gap_excerpt,
        "frames.csv": frames_path,
    }


def validate_failed_long_run(run: dict[str, Any]) -> None:
    summary = run["summary"]
    required = {
        "status": "FAIL",
        "warmup_seconds": 60,
        "duration_seconds": 1800,
        "host_acceptance": False,
        "external_analyzer_reconciliation": "PENDING",
    }
    for name, expected in required.items():
        if summary.get(name) != expected:
            fail(f"unexpected frozen long-run summary: {name}")
    if summary.get("frames_per_second", 0) < 6000:
        fail("frozen long run did not meet the throughput threshold")
    if (
        summary.get("event_gaps", 0) <= 0
        or summary.get("channel_gaps", 0) <= 0
        or summary.get("data_loss_dropped", 0) <= 0
    ):
        fail("frozen long run does not prove sequence/data loss")


def validate_qualified_long_run(run: dict[str, Any], data_loss: bytes) -> None:
    summary = run["summary"]
    required = {
        "status": "PARTIAL",
        "warmup_seconds": 60,
        "duration_seconds": 1800,
        "event_gaps": 0,
        "channel_gaps": 0,
        "intra_batch_discontinuities": 0,
        "cross_batch_discontinuities": 0,
        "forward_missing_records": 0,
        "backward_or_duplicate_records": 0,
        "device_drop_total": 0,
        "diagnostic_channel_drops": 0,
        "measurement_queue_drops": 0,
        "measurement_ring_drops": 0,
        "data_loss_events": 0,
        "data_loss_dropped": 0,
        "host_acceptance": True,
        "external_analyzer_reconciliation": "PENDING",
    }
    for name, expected in required.items():
        if summary.get(name) != expected:
            fail(f"unexpected qualified long-run summary: {name}")
    if summary.get("frames_per_second", 0) < 6000:
        fail("qualified long run did not meet the throughput threshold")
    if summary.get("latency_ns_p95", 5_000_001) > 5_000_000:
        fail("qualified long run exceeded the latency threshold")
    if summary.get("fit_residual_ns_p95", 1_000_001) > 1_000_000:
        fail("qualified long run exceeded the clock-fit residual threshold")
    window = run["measurement_window"]
    if abs(window.get("first_frame_delay_seconds", 10)) > 1:
        fail("qualified long run did not have traffic at measurement start")
    if abs(window.get("last_frame_offset_from_end_seconds", 10)) > 1:
        fail("qualified long run did not retain traffic through measurement end")
    if data_loss.decode("ascii").splitlines() != [DATA_LOSS_HEADER]:
        fail("qualified long-run data_loss.csv must contain only the stable header")


def validate_diagnostic_run(run: dict[str, Any], data_loss: bytes) -> None:
    summary = run["summary"]
    required = {
        "status": "FAIL",
        "warmup_seconds": 60,
        "duration_seconds": 600,
        "event_gaps": 0,
        "channel_gaps": 0,
        "data_loss_events": 0,
        "data_loss_dropped": 0,
        "host_acceptance": False,
        "external_analyzer_reconciliation": "PENDING",
    }
    for name, expected in required.items():
        if summary.get(name) != expected:
            fail(f"unexpected diagnostic summary: {name}")
    if summary.get("frames_per_second", 6000) >= 6000:
        fail("diagnostic run does not prove throughput below the frozen threshold")
    if run["frames"].get("frames_per_second_over_active_span", 0) < 6000:
        fail("diagnostic retained-frame span was also below 6000 frame/s")
    if data_loss.decode("ascii").splitlines() != [DATA_LOSS_HEADER]:
        fail("diagnostic data_loss.csv must contain only the stable header")


def make_run_manifest(
    evidence_id: str,
    command: str,
    result: str,
    run: dict[str, Any],
    files: dict[str, bytes | Path],
    firmware_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "evidence_id": evidence_id,
        "phase": "P3B",
        "command": command,
        "result": result,
        "firmware_evidence_sha256": firmware_sha256,
        "summary_sha256": sha256_bytes(files["summary.json"]),
        "diagnostics_sha256": sha256_bytes(files["diagnostics.csv"]),
        "pings_sha256": sha256_bytes(files["pings.csv"]),
        "frames_csv": run["frames"],
        "measurement_window": run["measurement_window"],
        "acceptance_observed": {
            name: run["summary"].get(name)
            for name in (
                "frames_per_second",
                "event_gaps",
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
                "external_analyzer_reconciliation",
            )
        },
    }


def write_package(
    path: Path, members: tuple[str, ...], data: dict[str, bytes | Path]
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.comment = b""
            for name in members:
                member = data[name]
                if isinstance(member, Path):
                    info = zip_info(name, compressed=True)
                    info.file_size = member.stat().st_size
                    with member.open("rb") as source, archive.open(info, "w") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                else:
                    archive.writestr(zip_info(name), member)
        temporary.replace(path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def package_reference(path: Path, members: tuple[str, ...]) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "members": list(members),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--long-run-dir",
        type=Path,
        default=ROOT / "artifacts/hil-2026-08-15/T-CAN-1M-30MIN",
    )
    parser.add_argument(
        "--qualified-run-dir",
        type=Path,
        default=ROOT
        / "artifacts/hil-2026-08-15/T-CAN-1M-30MIN-RERUN-105401",
    )
    parser.add_argument(
        "--diagnostic-dir",
        type=Path,
        default=ROOT / "artifacts/hil-2026-08-15/T-CAN-1M-10MIN-DIAG",
    )
    parser.add_argument(
        "--firmware-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json",
    )
    parser.add_argument(
        "--preflight-status",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-execution-status-2026-08-14.json",
    )
    parser.add_argument(
        "--long-run-reset",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-MCU-reset-30MIN-2026-08-15.txt",
    )
    parser.add_argument(
        "--diagnostic-reset",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-MCU-reset-10MIN-DIAG-2026-08-15.txt",
    )
    parser.add_argument(
        "--long-run-package",
        default="docs/evidence/phase3/P3B-HIL-30MIN-failure-2026-08-15.zip",
    )
    parser.add_argument(
        "--qualified-package",
        default="docs/evidence/phase3/P3B-HIL-30MIN-qualified-2026-08-15.zip",
    )
    parser.add_argument(
        "--diagnostic-package",
        default="docs/evidence/phase3/P3B-HIL-10MIN-diagnostic-2026-08-15.zip",
    )
    parser.add_argument(
        "--status",
        default="docs/evidence/phase3/P3B-HIL-load-status-2026-08-15.json",
    )
    parser.add_argument(
        "--capture-anchor",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-capture-tool-anchor-2026-08-15.json",
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
        "--operator-attestation",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-independent-analyzer-capability-2026-08-15.txt",
    )
    parser.add_argument(
        "--backpressure-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-backpressure-evidence-2026-08-15.json",
    )
    parser.add_argument(
        "--hotplug-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-PHYSICAL-USB-HOTPLUG-1CYCLE-2026-08-15.json",
    )
    parser.add_argument(
        "--bus-off-blocker",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-bus-off-fault-injection-blocker-2026-08-15.json",
    )
    parser.add_argument(
        "--analyzer-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/"
        "P3B-HIL-analyzer-low-rate-evidence-2026-08-15.json",
    )
    args = parser.parse_args()

    long_package = repository_output(args.long_run_package, "long-run package")
    qualified_package = repository_output(
        args.qualified_package, "qualified long-run package"
    )
    diagnostic_package = repository_output(
        args.diagnostic_package, "diagnostic package"
    )
    status_path = repository_output(args.status, "load status manifest")
    firmware_path = regular_file(args.firmware_evidence, "firmware evidence")
    preflight_path = regular_file(args.preflight_status, "preflight status")
    long_reset = regular_file(args.long_run_reset, "long-run reset transcript")
    diagnostic_reset = regular_file(
        args.diagnostic_reset, "diagnostic reset transcript"
    )
    capture_anchor = regular_file(args.capture_anchor, "capture tool anchor")
    capture_source = regular_file(args.capture_source, "capture source")
    capture_binary = regular_file(args.capture_binary, "capture binary")
    operator_attestation = regular_file(
        args.operator_attestation, "operator attestation"
    )
    backpressure_evidence = regular_file(
        args.backpressure_evidence, "backpressure evidence"
    )
    hotplug_evidence = regular_file(args.hotplug_evidence, "hotplug evidence")
    bus_off_blocker = regular_file(args.bus_off_blocker, "bus-off blocker evidence")
    analyzer_evidence = regular_file(args.analyzer_evidence, "analyzer evidence")
    firmware_sha256 = sha256_file(firmware_path)
    capture_anchor_bytes = capture_anchor.read_bytes()
    capture_anchor_value = json_object(capture_anchor_bytes, "capture tool anchor")
    expected_capture_source = {
        "commit": "afbf243e1b0e433deb9fad946dab7d4beb3b026a",
        "dirty": True,
        "member": "capture/can_hil_capture.rs",
        "sha256": sha256_file(capture_source),
        "size": capture_source.stat().st_size,
    }
    expected_capture_binary = {
        "member": "capture/can_hil_capture",
        "sha256": sha256_file(capture_binary),
        "size": capture_binary.stat().st_size,
    }
    if (
        capture_anchor_value.get("schema") != 1
        or capture_anchor_value.get("evidence_id")
        != "P3B-capture-tool-anchor-2026-08-15"
        or capture_anchor_value.get("phase") != "P3B"
        or capture_anchor_value.get("source") != expected_capture_source
        or capture_anchor_value.get("binary") != expected_capture_binary
        or capture_anchor_value.get("compiler")
        != "rustc 1.97.1 (8bab26f4f 2026-07-14)"
    ):
        fail("capture tool does not match immutable anchor")

    long_run, long_files = load_run(args.long_run_dir, "frozen long run")
    validate_failed_long_run(long_run)
    long_manifest = make_run_manifest(
        "P3B-HIL-30MIN-failure-2026-08-15",
        (
            "cd host && cargo run -p hpm-usb-can-core --release "
            "--example can_hil_capture -- 60 1800 "
            "../artifacts/hil-2026-08-15/T-CAN-1M-30MIN"
        ),
        "FAIL_SEQUENCE_AND_DATA_LOSS",
        long_run,
        long_files,
        firmware_sha256,
    )
    long_package_data = {
        "run-manifest.json": normalized_json(long_manifest),
        "summary.json": long_files["summary.json"],
        "diagnostics.csv": long_files["diagnostics.csv"],
        "pings.csv": long_files["pings.csv"],
        "frames.csv": long_files["frames.csv"],
        "channel-gap-excerpt.csv": long_files["channel-gap-excerpt.csv"],
        "jlink-reset.txt": long_reset.read_bytes(),
    }
    write_package(long_package, FAILED_LONG_RUN_MEMBERS, long_package_data)

    qualified_run, qualified_files = load_run(
        args.qualified_run_dir, "qualified frozen long run"
    )
    qualified_data_loss = regular_file(
        args.qualified_run_dir / "data_loss.csv",
        "qualified long-run data_loss.csv",
    ).read_bytes()
    validate_qualified_long_run(qualified_run, qualified_data_loss)
    qualified_manifest = make_run_manifest(
        "P3B-HIL-30MIN-qualified-2026-08-15",
        (
            "cd host && cargo run -p hpm-usb-can-core --release "
            "--example can_hil_capture -- 60 1800 "
            "../artifacts/hil-2026-08-15/T-CAN-1M-30MIN-RERUN-105401"
        ),
        "PASS_HOST_LOAD_ACCEPTANCE",
        qualified_run,
        qualified_files,
        firmware_sha256,
    )
    qualified_manifest["data_loss_csv_sha256"] = sha256_bytes(qualified_data_loss)
    qualified_manifest["capture_tool"] = {
        "source_commit": "afbf243e1b0e433deb9fad946dab7d4beb3b026a",
        "source_dirty": True,
        "anchor_member": "capture/capture-tool-anchor.json",
        "anchor_sha256": sha256_bytes(capture_anchor_bytes),
        "source_member": "capture/can_hil_capture.rs",
        "source_sha256": sha256_file(capture_source),
        "binary_member": "capture/can_hil_capture",
        "binary_sha256": sha256_file(capture_binary),
        "binary_size": capture_binary.stat().st_size,
        "compiler": "rustc 1.97.1 (8bab26f4f 2026-07-14)",
    }
    qualified_manifest["operator_attestation_sha256"] = sha256_file(
        operator_attestation
    )
    qualified_package_data = {
        "run-manifest.json": normalized_json(qualified_manifest),
        "summary.json": qualified_files["summary.json"],
        "diagnostics.csv": qualified_files["diagnostics.csv"],
        "pings.csv": qualified_files["pings.csv"],
        "frames.csv": qualified_files["frames.csv"],
        "data_loss.csv": qualified_data_loss,
        "capture/capture-tool-anchor.json": capture_anchor_bytes,
        "capture/can_hil_capture.rs": capture_source.read_bytes(),
        "capture/can_hil_capture": capture_binary.read_bytes(),
        "operator-attestation.txt": operator_attestation.read_bytes(),
    }
    write_package(
        qualified_package,
        QUALIFIED_LONG_RUN_MEMBERS,
        qualified_package_data,
    )

    diagnostic_run, diagnostic_files = load_run(
        args.diagnostic_dir, "10-minute diagnostic run"
    )
    data_loss = regular_file(
        args.diagnostic_dir / "data_loss.csv", "diagnostic data_loss.csv"
    ).read_bytes()
    validate_diagnostic_run(diagnostic_run, data_loss)
    diagnostic_manifest = make_run_manifest(
        "P3B-HIL-10MIN-diagnostic-2026-08-15",
        (
            "cd host && cargo run -p hpm-usb-can-core --release "
            "--example can_hil_capture -- 60 600 "
            "../artifacts/hil-2026-08-15/T-CAN-1M-10MIN-DIAG"
        ),
        "FAIL_FIXED_WINDOW_THROUGHPUT",
        diagnostic_run,
        diagnostic_files,
        firmware_sha256,
    )
    diagnostic_manifest["data_loss_csv_sha256"] = sha256_bytes(data_loss)
    diagnostic_package_data = {
        "run-manifest.json": normalized_json(diagnostic_manifest),
        "summary.json": diagnostic_files["summary.json"],
        "diagnostics.csv": diagnostic_files["diagnostics.csv"],
        "pings.csv": diagnostic_files["pings.csv"],
        "frames.csv": diagnostic_files["frames.csv"],
        "data_loss.csv": data_loss,
        "jlink-reset.txt": diagnostic_reset.read_bytes(),
    }
    write_package(diagnostic_package, DIAGNOSTIC_MEMBERS, diagnostic_package_data)

    status = {
        "schema": 1,
        "evidence_id": "P3B-HIL-load-status-2026-08-15",
        "phase": "P3B",
        "qualification_status": "PARTIAL",
        "p4e_gate": "BLOCKED",
        "firmware_evidence": {
            "path": firmware_path.relative_to(ROOT).as_posix(),
            "sha256": firmware_sha256,
        },
        "preflight_status": {
            "path": preflight_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(preflight_path),
        },
        "operator_configuration_attestation": {
            "date": "2026-08-15",
            "can_bitrate_bits_per_second": 1_000_000,
            "generator_minimum_frames_per_second": 6000,
            "generator_ack_mode": "normal_active",
            "independent_analyzer_connected": True,
            "independent_analyzer_export": "archived:analyzer-log.txt",
            "independent_analyzer_6000fps_log_export": False,
            "independent_analyzer_max_log_frames_per_second": 1000,
            "independent_analyzer_low_rate_observed_frames_per_second": 63.661,
            "independent_analyzer_low_rate_reconciliation": "PASS_WITH_LIMITATION",
            "high_rate_evidence_mode": "dut_host_capture_and_firmware_diagnostics",
            "attestation": {
                "path": operator_attestation.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(operator_attestation),
            },
        },
        "frozen_profile": {
            "long_run_started": True,
            "result": "PASS_HOST_LOAD_ACCEPTANCE",
            "load_gate": "PASS",
            "required_command": qualified_manifest["command"],
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
            "blocked_reason": (
                "The encoded 1800-second host/device load gate passed. Overall P3B "
                "remains PARTIAL because bus-off/manual fault injection is blocked "
                "by the absence of a controlled safe test hook. The low-rate "
                "independent analyzer reconciliation is complete with explicit "
                "timestamp-resolution and high-rate-coverage limitations."
            ),
        },
        "supplemental_evidence": {
            "backpressure": {
                "path": backpressure_evidence.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(backpressure_evidence),
            },
            "physical_usb_hotplug": {
                "path": hotplug_evidence.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(hotplug_evidence),
            },
            "bus_off_fault_injection_blocker": {
                "path": bus_off_blocker.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(bus_off_blocker),
            },
            "independent_analyzer_low_rate": {
                "path": analyzer_evidence.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(analyzer_evidence),
            },
        },
        "runs": {
            "frozen_30_min_initial_failure": {
                "result": long_manifest["result"],
                "package": package_reference(
                    long_package, FAILED_LONG_RUN_MEMBERS
                ),
                "frames_csv": long_manifest["frames_csv"],
                "measurement_window": long_manifest["measurement_window"],
                "acceptance_observed": long_manifest["acceptance_observed"],
            },
            "diagnostic_10_min": {
                "result": diagnostic_manifest["result"],
                "package": package_reference(
                    diagnostic_package, DIAGNOSTIC_MEMBERS
                ),
                "frames_csv": diagnostic_manifest["frames_csv"],
                "measurement_window": diagnostic_manifest["measurement_window"],
                "acceptance_observed": diagnostic_manifest["acceptance_observed"],
            },
            "frozen_30_min_qualified": {
                "result": qualified_manifest["result"],
                "package": package_reference(
                    qualified_package, QUALIFIED_LONG_RUN_MEMBERS
                ),
                "frames_csv": qualified_manifest["frames_csv"],
                "measurement_window": qualified_manifest["measurement_window"],
                "acceptance_observed": qualified_manifest["acceptance_observed"],
            },
        },
        "evidence_boundary": {
            "statement": (
                "The qualified rerun passed every encoded host/device acceptance "
                "criterion over the complete 1800-second measurement window. A "
                "separate export-capable low-rate independent analyzer window "
                "reconciled all frames and the selected 1 Mbit/s nominal bitrate. "
                "No independent high-rate timestamp stream is claimed."
            ),
            "pending": [
                "bus-off/manual fault injection",
            ],
            "completed": [
                "1 Mbit/s external CAN generator run at >=6000 frame/s for 1800 seconds",
                "USB backpressure recovery under CAN load",
                "EVENT-domain state/drop reconciliation",
                "physical USB disconnect/reconnect (1 cycle)",
                "independent analyzer low-rate frame/content, coarse timestamp/rate, and nominal 1 Mbit/s configuration reconciliation",
            ],
            "limitations": [
                "No independent analyzer per-frame timestamp export exists for the 6000 frame/s run.",
                "The independent analyzer export-capable run observed approximately 63.661 frame/s and does not independently cover the 6000 frame/s load profile.",
                "The independent analyzer timestamp text has 1 ms resolution and logger/scheduler jitter; sub-millisecond accuracy is not claimed.",
                "The archived analyzer screenshot proves the selected 1 Mbit/s nominal arbitration bitrate, not electrical waveform shape, sample point, or oscillator tolerance.",
                "EVENT-domain DATA_LOSS exactly reconciles missing EVENT sequences, but cannot exactly attribute the 90159 missing CAN channel records inside dropped batches.",
                "The capture executable was built from an archived dirty source snapshot; its source and binary are embedded in the qualified package.",
                "Firmware identity is bound to the prior immutable Program+Verify and flash-readback evidence rather than a new flash immediately before this rerun.",
            ],
        },
    }
    with tempfile.NamedTemporaryFile(
        dir=status_path.parent, prefix=f".{status_path.name}.", delete=False
    ) as stream:
        temporary_status = Path(stream.name)
    try:
        temporary_status.write_bytes(normalized_json(status))
        temporary_status.replace(status_path)
        status_path.chmod(0o644)
    finally:
        temporary_status.unlink(missing_ok=True)

    print(
        "PASS qualification=PARTIAL p4e=BLOCKED load_gate=PASS "
        f"qualified={qualified_manifest['result']} "
        f"initial={long_manifest['result']} diagnostic={diagnostic_manifest['result']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
