#!/usr/bin/env python3
"""Validate immutable P3B CAN-load evidence packages and gate status."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.phase3.external_artifact_index import validate_detached_reference
except ModuleNotFoundError:  # Direct execution adds scripts/phase3, not repo root.
    from external_artifact_index import validate_detached_reference


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(
    "docs/evidence/phase3/P3B-HIL-load-status-2026-08-15.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FAILED_LONG_RUN_MEMBERS = [
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "frames.csv",
    "channel-gap-excerpt.csv",
    "jlink-reset.txt",
]
QUALIFIED_LONG_RUN_MEMBERS = [
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
]
DIAGNOSTIC_MEMBERS = [
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "frames.csv",
    "data_loss.csv",
    "jlink-reset.txt",
]
DATA_LOSS_HEADER = (
    "host_ingest_ns,device_tick,event_sequence,channel,source,sequence_domain,reason,"
    "config_generation,first_dropped_sequence,last_dropped_sequence,dropped_count"
)
EXPECTED_ACCEPTANCE = {
    "minimum_frames_per_second": 6000,
    "event_sequence_gaps": 0,
    "channel_sequence_gaps": 0,
    "queue_drops": 0,
    "ring_drops": 0,
    "device_drops": 0,
    "latency_p95_ns_max": 5_000_000,
    "clock_fit_residual_p95_ns_max": 1_000_000,
}
EXPECTED_PENDING = [
    "bus-off/manual fault injection",
]
EXPECTED_COMPLETED = [
    "1 Mbit/s external CAN generator run at >=6000 frame/s for 1800 seconds",
    "USB backpressure recovery under CAN load",
    "EVENT-domain state/drop reconciliation",
    "physical USB disconnect/reconnect (1 cycle)",
    "independent analyzer low-rate frame/content, coarse timestamp/rate, and nominal 1 Mbit/s configuration reconciliation",
    "controlled bus-off attempt with a silent analyzer reached error-passive at TEC 128 and safely timed out without bus-off",
]
EXPECTED_CAPTURE_ANCHOR_SHA256 = (
    "26d53f98e630eccaf1c9dfc42c3c49f36bc10a5e84c744ea7eb7b28679717108"
)
EXPECTED_STATEMENT = (
    "The qualified rerun passed every encoded host/device acceptance "
    "criterion over the complete 1800-second measurement window. A "
    "separate export-capable low-rate independent analyzer window "
    "reconciled all frames and the selected 1 Mbit/s nominal bitrate. "
    "No independent high-rate timestamp stream is claimed."
)
EXPECTED_RUN_SOURCE_HASHES = {
    "initial_failure": {
        "summary.json": "af540a32970cef8d415e5c23526b9d419d2bd2d741bdf500376efa5266c8da09",
        "diagnostics.csv": "3a2d05f7911799195a80f44c83c53221405cc723376fc7091278199c81d0c6b0",
        "pings.csv": "574e1a7debeea2fd089cad4e2cbf46966bbb1b4b709469640da2304dd39b3553",
        "frames.csv": "374b8c5893a83fe6b3d53c99ec8a1e6a9a87a13f317160c154a6c65d44362117",
        "channel-gap-excerpt.csv": "fe125dbf94c287eb1806db978836b2d0ee2b5b1753df8acd57215ab130449335",
        "jlink-reset.txt": "3a925857ac875f6628e55b7ca641847e6604b64ab496a4cf6bf54a651c3df6f2",
    },
    "diagnostic": {
        "summary.json": "3a62222a13a5c0487f2919dbc030e3364ab39448d4591f81f7f1d51372e4d739",
        "diagnostics.csv": "bbadb91090332841462ac75eea5c863d6b7cee7e38fdd394dac3b930b88ac3a6",
        "pings.csv": "e38f2a9b6dcfb934ff2b6cb22ccb733484df84c61023dfd15ad06c0f1b5cdeb7",
        "frames.csv": "e3071ec1a7e1ff78d52ec9d2c5d58024c80c0c902de17dac42ce6e689757fb4f",
        "data_loss.csv": "01af27eb48d98a511d7f535f9566a2aa0017cd19e3be53f85d7453558238fd41",
        "jlink-reset.txt": "bcfbe250e0e2cfb7797b1bb3be232b82e6e74694cab9786135c78b6608661471",
    },
    "qualified": {
        "summary.json": "194c49ac193eb34a8843c6df14688d0f0cdc70c1e230611eb4e5d736c7bcc16f",
        "diagnostics.csv": "7801796b8fe8f3320053160031973bb9ad2ecb0c850e2adaa6308406126b5143",
        "pings.csv": "f31d0fe3a6b22c81b6ca7d3d0ed32e67f73c4136b6a72cd282b14cf1900a132b",
        "frames.csv": "700436c934d28220243ccc093e1107adb21343b7224a34dcc56b1df517ff5bf9",
        "data_loss.csv": "01af27eb48d98a511d7f535f9566a2aa0017cd19e3be53f85d7453558238fd41",
        "capture/capture-tool-anchor.json": EXPECTED_CAPTURE_ANCHOR_SHA256,
        "capture/can_hil_capture.rs": "6944d5150086a17605e37c10e4d220258eff964783ad7b9544b9c53181636541",
        "capture/can_hil_capture": "1791cb97ea8dd37abbae04cab7bb7a8a6cb0d98898bc81637d6de7549b3e8587",
        "operator-attestation.txt": "fa9e80b5c532bb5c898e58ebe6741d29a6fe58ff4c3d4546abca32ddd5674c9b",
    },
}
_SHA256_CACHE: dict[tuple[str, int, int, int], str] = {}
_PACKAGE_CACHE: dict[
    tuple[str, int, int, int], tuple[dict[str, bytes], dict[str, Any]]
] = {}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_cache_key(path: Path) -> tuple[str, int, int, int]:
    stat = path.stat()
    return (str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns)


def sha256_file(path: Path) -> str:
    key = file_cache_key(path)
    cached = _SHA256_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _SHA256_CACHE[key] = value
    return value


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


def read_json_bytes(data: bytes, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def read_json_file(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        return read_json_bytes(path.read_bytes(), label, errors)
    except OSError as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}


def nested_validator(name: str, root: Path, relative: Path) -> list[str]:
    module_path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"p3b_load_nested_{name}", module_path)
    if spec is None or spec.loader is None:
        return [f"unable to load nested validator: {name}"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate(root, relative)


def validate_zip_info(
    info: zipfile.ZipInfo, expected: str, label: str, errors: list[str]
) -> None:
    safe_relative_path(info.filename, f"{label} member", errors)
    if info.filename != expected:
        errors.append(f"{label} member list mismatch")
    expected_compression = (
        zipfile.ZIP_DEFLATED if expected == "frames.csv" else zipfile.ZIP_STORED
    )
    if (
        info.date_time != FIXED_ZIP_TIME
        or info.create_system != 3
        or info.compress_type != expected_compression
        or info.flag_bits != 0
        or info.internal_attr != 0
        or info.external_attr != 0o100644 << 16
        or info.extra
        or info.comment
    ):
        errors.append(f"{label} member metadata mismatch: {info.filename}")
    if expected == "frames.csv":
        if not 0 < info.file_size <= 750 * 1024 * 1024:
            errors.append(f"{label} frames.csv size is invalid")
        if not 0 < info.compress_size <= 128 * 1024 * 1024:
            errors.append(f"{label} frames.csv compressed size is invalid")
    elif not 0 < info.file_size <= 1024 * 1024:
        errors.append(f"{label} package member size is invalid: {info.filename}")


def iso_utc_from_ns(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1_000_000_000, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def analyze_archived_frames(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, label: str, errors: list[str]
) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    previous_sequence = 0
    gap_count = 0
    first_values: list[str] | None = None
    last_values: list[str] | None = None
    try:
        with archive.open(info) as stream:
            header = stream.readline()
            digest.update(header)
            if header.rstrip(b"\r\n").decode("ascii") != (
                "host_ingest_ns,device_tick,channel_sequence,arbitration_id,flags,"
                "dlc,device_drop_total,event_sequence,payload_hex"
            ):
                errors.append(f"{label} frames.csv header mismatch")
                return {}
            for raw_line in stream:
                digest.update(raw_line)
                values = next(csv.reader([raw_line.decode("ascii")]))
                if len(values) != 9:
                    errors.append(f"{label} frames.csv row width mismatch")
                    return {}
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
                previous_sequence = sequence
    except (UnicodeDecodeError, ValueError, csv.Error, RuntimeError, OSError) as exc:
        errors.append(f"{label} frames.csv cannot be replayed: {exc}")
        return {}
    if first_values is None or last_values is None:
        errors.append(f"{label} frames.csv contains no data rows")
        return {}
    active_span_seconds = (
        int(last_values[0]) - int(first_values[0])
    ) / 1_000_000_000
    return {
        "archived": True,
        "member": "frames.csv",
        "compression": "zip-deflate",
        "sha256": digest.hexdigest(),
        "size": info.file_size,
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


def validate_package(
    root: Path,
    reference: object,
    expected_members: list[str],
    label: str,
    errors: list[str],
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any] | None]:
    if not isinstance(reference, dict):
        errors.append(f"{label} package reference is missing")
        return {}, {}, None
    relative = safe_relative_path(reference.get("path"), f"{label} package", errors)
    if relative is None:
        return {}, {}, None
    candidate = root / relative
    if not candidate.exists():
        return {}, {}, validate_detached_reference(root, reference, errors)
    package_path = repository_file(root, relative, f"{label} package", errors)
    if package_path is None:
        return {}, {}, None
    if reference.get("size") != package_path.stat().st_size:
        errors.append(f"{label} package size mismatch")
    if reference.get("sha256") != sha256_file(package_path):
        errors.append(f"{label} package SHA-256 mismatch")
    if reference.get("members") != expected_members:
        errors.append(f"{label} package member reference mismatch")
    cache_key = file_cache_key(package_path)
    cached = _PACKAGE_CACHE.get(cache_key)
    if cached is not None:
        members, frames = cached
        return dict(members), dict(frames), None
    members: dict[str, bytes] = {}
    frames: dict[str, Any] = {}
    package_error_count = len(errors)
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append(f"{label} package archive comment is not allowed")
            if archive.namelist() != expected_members:
                errors.append(f"{label} package member list mismatch")
            for info, expected in zip(
                archive.infolist(), expected_members, strict=False
            ):
                validate_zip_info(info, expected, label, errors)
            for name in expected_members:
                if name == "frames.csv":
                    frames = analyze_archived_frames(
                        archive, archive.getinfo(name), label, errors
                    )
                else:
                    members[name] = archive.read(name)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid {label} package: {exc}")
    if len(errors) == package_error_count:
        _PACKAGE_CACHE[cache_key] = (dict(members), dict(frames))
    return members, frames, None


def validate_detached_run(
    status_run: dict[str, Any],
    artifact: dict[str, Any],
    expected_result: str,
    kind: str,
    label: str,
    errors: list[str],
) -> None:
    frames = status_run.get("frames_csv")
    observed = status_run.get("acceptance_observed")
    window = status_run.get("measurement_window")
    if not isinstance(frames, dict) or not isinstance(observed, dict) or not isinstance(window, dict):
        errors.append(f"{label} detached key records are missing")
        return
    expected_excerpt = {
        "source_evidence": DEFAULT_MANIFEST.as_posix(),
        "run": {
            "initial_failure": "frozen_30_min_initial_failure",
            "diagnostic": "diagnostic_10_min",
            "qualified": "frozen_30_min_qualified",
        }[kind],
        "result": expected_result,
        "frames_csv_sha256": frames.get("sha256"),
        "frames_csv_size": frames.get("size"),
        "frames_csv_row_count": frames.get("row_count"),
        "host_acceptance": observed.get("host_acceptance"),
        "measurement_duration_seconds": window.get("duration_seconds"),
    }
    if artifact.get("key_excerpt") != expected_excerpt:
        errors.append(f"{label} detached key excerpt mismatch")
    if frames.get("sha256") != EXPECTED_RUN_SOURCE_HASHES[kind]["frames.csv"]:
        errors.append(f"{label} immutable source hash mismatch: frames.csv")
    if frames.get("archived") is not True or frames.get("member") != "frames.csv":
        errors.append(f"{label} detached frames metadata mismatch")
    if not isinstance(frames.get("size"), int) or frames["size"] <= 0:
        errors.append(f"{label} frames.csv size is invalid")
    if not isinstance(frames.get("row_count"), int) or frames["row_count"] <= 0:
        errors.append(f"{label} frames.csv row count is invalid")
    expected_host_acceptance = kind == "qualified"
    if observed.get("host_acceptance") is not expected_host_acceptance:
        errors.append(f"{label} detached host acceptance mismatch")
    if not isinstance(window.get("duration_seconds"), (int, float)) or window["duration_seconds"] <= 0:
        errors.append(f"{label} measurement duration is invalid")


def validate_frames_metadata(
    manifest: dict[str, Any],
    status_run: dict[str, Any],
    archived_frames: dict[str, Any],
    summary: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    frames = manifest.get("frames_csv")
    if not isinstance(frames, dict):
        errors.append(f"{label} run manifest requires frames_csv")
        return
    if frames != status_run.get("frames_csv"):
        errors.append(f"{label} frames metadata mismatch between package and status")
    if frames != archived_frames:
        errors.append(f"{label} archived frames.csv metadata mismatch")
    if frames.get("archived") is not True:
        errors.append(f"{label} frames.csv must be archived")
    if frames.get("member") != "frames.csv":
        errors.append(f"{label} frames.csv member mismatch")
    if frames.get("compression") != "zip-deflate":
        errors.append(f"{label} frames.csv compression mismatch")
    digest = frames.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append(f"{label} frames.csv SHA-256 is invalid")
    if frames.get("size", 0) <= 0:
        errors.append(f"{label} frames.csv size is invalid")
    if frames.get("row_count") != summary.get("frames"):
        errors.append(f"{label} frames.csv row count mismatch")
    if frames.get("channel_gap_count") != summary.get("channel_gaps"):
        errors.append(f"{label} frames.csv channel gap count mismatch")
    for name in ("measurement_first_frame_utc", "measurement_last_frame_utc"):
        if not isinstance(frames.get(name), str) or not frames[name].endswith("Z"):
            errors.append(f"{label} {name} is invalid")
    if frames.get("active_frame_span_seconds", 0) <= 0:
        errors.append(f"{label} active frame span is invalid")
    if frames.get("frames_per_second_over_active_span", 0) <= 0:
        errors.append(f"{label} active-span frame rate is invalid")


def validate_run(
    root: Path,
    status_run: object,
    expected_result: str,
    expected_members: list[str],
    label: str,
    kind: str,
    errors: list[str],
) -> None:
    if not isinstance(status_run, dict):
        errors.append(f"status requires {label} run")
        return
    if status_run.get("result") != expected_result:
        errors.append(f"{label} result mismatch")
    members, archived_frames, detached_artifact = validate_package(
        root, status_run.get("package"), expected_members, label, errors
    )
    if detached_artifact is not None:
        validate_detached_run(
            status_run, detached_artifact, expected_result, kind, label, errors
        )
        return
    if not members or not archived_frames:
        return
    manifest = read_json_bytes(members["run-manifest.json"], f"{label} run manifest", errors)
    summary = read_json_bytes(members["summary.json"], f"{label} summary", errors)
    if manifest.get("result") != expected_result:
        errors.append(f"{label} packaged result mismatch")
    if manifest.get("summary_sha256") != sha256_bytes(members["summary.json"]):
        errors.append(f"{label} summary SHA-256 mismatch")
    if manifest.get("diagnostics_sha256") != sha256_bytes(members["diagnostics.csv"]):
        errors.append(f"{label} diagnostics SHA-256 mismatch")
    if manifest.get("pings_sha256") != sha256_bytes(members["pings.csv"]):
        errors.append(f"{label} pings SHA-256 mismatch")
    if manifest.get("acceptance_observed") != status_run.get("acceptance_observed"):
        errors.append(f"{label} observed acceptance mismatch")
    measurement_window = manifest.get("measurement_window")
    if not isinstance(measurement_window, dict):
        errors.append(f"{label} run manifest requires measurement_window")
        measurement_window = {}
    if measurement_window != status_run.get("measurement_window"):
        errors.append(
            f"{label} measurement window mismatch between package and status"
        )
    if measurement_window.get("duration_seconds", 0) <= 0:
        errors.append(f"{label} measurement duration is invalid")
    validate_frames_metadata(
        manifest, status_run, archived_frames, summary, label, errors
    )
    expected_hashes = EXPECTED_RUN_SOURCE_HASHES[kind]
    for name, expected_hash in expected_hashes.items():
        actual_hash = (
            archived_frames.get("sha256")
            if name == "frames.csv"
            else sha256_bytes(members[name])
        )
        if actual_hash != expected_hash:
            errors.append(f"{label} immutable source hash mismatch: {name}")
    if kind != "qualified":
        reset_text = members["jlink-reset.txt"].decode("utf-8", errors="replace")
        if "J-Link>r" not in reset_text or "J-Link>g" not in reset_text:
            errors.append(f"{label} reset transcript is incomplete")
        if "loadfile" in reset_text.lower():
            errors.append(f"{label} reset transcript unexpectedly contains a flash load")

    if kind == "initial_failure":
        expected = {
            "status": "FAIL",
            "warmup_seconds": 60,
            "duration_seconds": 1800,
            "host_acceptance": False,
        }
        for name, value in expected.items():
            if summary.get(name) != value:
                errors.append(f"{label} summary mismatch: {name}")
        if summary.get("frames_per_second", 0) < 6000:
            errors.append(f"{label} must record throughput at or above 6000 frame/s")
        if (
            summary.get("event_gaps", 0) <= 0
            or summary.get("channel_gaps", 0) <= 0
            or summary.get("data_loss_dropped", 0) <= 0
        ):
            errors.append(f"{label} must record sequence and data loss")
        if members["channel-gap-excerpt.csv"].count(b"\n") < 3:
            errors.append(f"{label} channel gap excerpt is incomplete")
        if abs(measurement_window.get("first_frame_delay_seconds", 10)) > 1:
            errors.append(f"{label} must show traffic present at window start")
    elif kind == "diagnostic":
        expected = {
            "status": "FAIL",
            "warmup_seconds": 60,
            "duration_seconds": 600,
            "event_gaps": 0,
            "channel_gaps": 0,
            "data_loss_events": 0,
            "data_loss_dropped": 0,
            "host_acceptance": False,
        }
        for name, value in expected.items():
            if summary.get(name) != value:
                errors.append(f"{label} summary mismatch: {name}")
        if summary.get("frames_per_second", 6000) >= 6000:
            errors.append(f"{label} must record throughput below 6000 frame/s")
        if manifest.get("frames_csv", {}).get(
            "frames_per_second_over_active_span", 0
        ) < 6000:
            errors.append(
                f"{label} must record active-span throughput at or above 6000 frame/s"
            )
        if measurement_window.get("first_frame_delay_seconds", 0) < 20:
            errors.append(f"{label} must record the delayed first frame")
        if members["data_loss.csv"].decode("ascii").splitlines() != [
            DATA_LOSS_HEADER
        ]:
            errors.append(f"{label} data_loss.csv mismatch")
        if manifest.get("data_loss_csv_sha256") != sha256_bytes(
            members["data_loss.csv"]
        ):
            errors.append(f"{label} data_loss.csv SHA-256 mismatch")
    elif kind == "qualified":
        expected = {
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
        for name, value in expected.items():
            if summary.get(name) != value:
                errors.append(f"{label} summary mismatch: {name}")
        if summary.get("frames_per_second", 0) < 6000:
            errors.append(f"{label} must record throughput at or above 6000 frame/s")
        if summary.get("latency_ns_p95", 5_000_001) > 5_000_000:
            errors.append(f"{label} exceeds the latency threshold")
        if summary.get("fit_residual_ns_p95", 1_000_001) > 1_000_000:
            errors.append(f"{label} exceeds the clock-fit residual threshold")
        if abs(measurement_window.get("first_frame_delay_seconds", 10)) > 1:
            errors.append(f"{label} must show traffic present at window start")
        if abs(measurement_window.get("last_frame_offset_from_end_seconds", 10)) > 1:
            errors.append(f"{label} must show traffic present through window end")
        if members["data_loss.csv"].decode("ascii").splitlines() != [
            DATA_LOSS_HEADER
        ]:
            errors.append(f"{label} data_loss.csv mismatch")
        if manifest.get("data_loss_csv_sha256") != sha256_bytes(
            members["data_loss.csv"]
        ):
            errors.append(f"{label} data_loss.csv SHA-256 mismatch")
        capture = manifest.get("capture_tool")
        if not isinstance(capture, dict):
            errors.append(f"{label} run manifest requires capture tool evidence")
            capture = {}
        archived_anchor = members["capture/capture-tool-anchor.json"]
        anchor_path = repository_file(
            root,
            "docs/evidence/phase3/P3B-capture-tool-anchor-2026-08-15.json",
            "capture tool anchor",
            errors,
        )
        if sha256_bytes(archived_anchor) != EXPECTED_CAPTURE_ANCHOR_SHA256:
            errors.append(f"{label} immutable capture tool anchor hash mismatch")
        if anchor_path is not None:
            if sha256_file(anchor_path) != EXPECTED_CAPTURE_ANCHOR_SHA256:
                errors.append("versioned capture tool anchor hash mismatch")
            if anchor_path.read_bytes() != archived_anchor:
                errors.append(
                    f"{label} versioned capture tool anchor differs from archived anchor"
                )
        expected_capture = {
            "source_commit": "afbf243e1b0e433deb9fad946dab7d4beb3b026a",
            "source_dirty": True,
            "anchor_member": "capture/capture-tool-anchor.json",
            "anchor_sha256": EXPECTED_CAPTURE_ANCHOR_SHA256,
            "source_member": "capture/can_hil_capture.rs",
            "source_sha256": "6944d5150086a17605e37c10e4d220258eff964783ad7b9544b9c53181636541",
            "binary_member": "capture/can_hil_capture",
            "binary_sha256": "1791cb97ea8dd37abbae04cab7bb7a8a6cb0d98898bc81637d6de7549b3e8587",
            "binary_size": 727744,
            "compiler": "rustc 1.97.1 (8bab26f4f 2026-07-14)",
        }
        if capture != expected_capture:
            errors.append(f"{label} capture tool evidence mismatch")
        capture_anchor = read_json_bytes(
            archived_anchor, f"{label} capture tool anchor", errors
        )
        if capture_anchor != {
            "schema": 1,
            "evidence_id": "P3B-capture-tool-anchor-2026-08-15",
            "phase": "P3B",
            "source": {
                "commit": expected_capture["source_commit"],
                "dirty": expected_capture["source_dirty"],
                "member": expected_capture["source_member"],
                "sha256": expected_capture["source_sha256"],
                "size": len(members["capture/can_hil_capture.rs"]),
            },
            "binary": {
                "member": expected_capture["binary_member"],
                "sha256": expected_capture["binary_sha256"],
                "size": expected_capture["binary_size"],
            },
            "compiler": expected_capture["compiler"],
        }:
            errors.append(f"{label} capture tool anchor content mismatch")
        if sha256_bytes(
            members["capture/can_hil_capture.rs"]
        ) != expected_capture["source_sha256"]:
            errors.append(f"{label} capture source does not match immutable anchor")
        if sha256_bytes(
            members["capture/can_hil_capture"]
        ) != expected_capture["binary_sha256"]:
            errors.append(f"{label} capture binary does not match immutable anchor")
        if manifest.get("operator_attestation_sha256") != sha256_bytes(
            members["operator-attestation.txt"]
        ):
            errors.append(f"{label} operator attestation SHA-256 mismatch")
    else:
        errors.append(f"{label} has unsupported validation kind")


def validate(root: Path, manifest_relative: Path = DEFAULT_MANIFEST) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    manifest_path = repository_file(
        root, manifest_relative.as_posix(), "load status manifest", errors
    )
    if manifest_path is None:
        return errors
    status = read_json_file(manifest_path, "load status manifest", errors)
    if status.get("schema") != 1:
        errors.append("unsupported load status schema")
    if status.get("evidence_id") != "P3B-HIL-load-status-2026-08-15":
        errors.append("unexpected load status evidence ID")
    if status.get("phase") != "P3B":
        errors.append("load status phase must be P3B")
    if status.get("qualification_status") != "PARTIAL":
        errors.append("P3B qualification must remain PARTIAL")
    if status.get("p4e_gate") != "BLOCKED":
        errors.append("P4E gate must remain BLOCKED")

    firmware = status.get("firmware_evidence")
    if not isinstance(firmware, dict):
        errors.append("load status requires firmware evidence")
        firmware = {}
    firmware_path = repository_file(
        root, firmware.get("path"), "firmware evidence", errors
    )
    if firmware_path is not None:
        if firmware.get("sha256") != sha256_file(firmware_path):
            errors.append("firmware evidence SHA-256 mismatch")
        for error in nested_validator(
            "validate_hil_firmware_evidence.py",
            root,
            firmware_path.relative_to(root),
        ):
            errors.append(f"firmware evidence: {error}")

    preflight = status.get("preflight_status")
    if not isinstance(preflight, dict):
        errors.append("load status requires preflight status")
        preflight = {}
    preflight_path = repository_file(
        root, preflight.get("path"), "preflight status", errors
    )
    if preflight_path is not None:
        if preflight.get("sha256") != sha256_file(preflight_path):
            errors.append("preflight status SHA-256 mismatch")
        for error in nested_validator(
            "validate_p3b_execution_status.py",
            root,
            preflight_path.relative_to(root),
        ):
            errors.append(f"preflight status: {error}")

    frozen = status.get("frozen_profile")
    if not isinstance(frozen, dict):
        errors.append("load status requires frozen profile")
        frozen = {}
    if frozen.get("long_run_started") is not True:
        errors.append("load status must record that the long run was started")
    if frozen.get("result") != "PASS_HOST_LOAD_ACCEPTANCE":
        errors.append("frozen profile result mismatch")
    if frozen.get("load_gate") != "PASS":
        errors.append("frozen profile load gate must be PASS")
    if frozen.get("acceptance") != EXPECTED_ACCEPTANCE:
        errors.append("frozen profile acceptance mismatch")
    command = frozen.get("required_command")
    if not isinstance(command, str) or "can_hil_capture -- 60 1800" not in command:
        errors.append("frozen profile command mismatch")
    reason = frozen.get("blocked_reason")
    if not isinstance(reason, str) or "low-rate independent analyzer" not in reason:
        errors.append(
            "frozen profile blocked reason must record the completed low-rate analyzer scope"
        )
    if (
        not isinstance(reason, str)
        or "TIMEOUT_CLEANED_NOT_BUS_OFF" not in reason
        or "active bit/form/stuff-error" not in reason
    ):
        errors.append(
            "frozen profile blocked reason must reference the authoritative "
            "non-PASS bus-off attempt and required active fault source"
        )

    runs = status.get("runs")
    if not isinstance(runs, dict):
        errors.append("load status requires runs")
        runs = {}
    validate_run(
        root,
        runs.get("frozen_30_min_initial_failure"),
        "FAIL_SEQUENCE_AND_DATA_LOSS",
        FAILED_LONG_RUN_MEMBERS,
        "initial frozen long run",
        "initial_failure",
        errors,
    )
    validate_run(
        root,
        runs.get("diagnostic_10_min"),
        "FAIL_FIXED_WINDOW_THROUGHPUT",
        DIAGNOSTIC_MEMBERS,
        "diagnostic run",
        "diagnostic",
        errors,
    )
    validate_run(
        root,
        runs.get("frozen_30_min_qualified"),
        "PASS_HOST_LOAD_ACCEPTANCE",
        QUALIFIED_LONG_RUN_MEMBERS,
        "qualified frozen long run",
        "qualified",
        errors,
    )

    operator = status.get("operator_configuration_attestation")
    if not isinstance(operator, dict):
        errors.append("load status requires operator configuration attestation")
        operator = {}
    expected_operator = {
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
    }
    operator_attestation = operator.get("attestation")
    operator_without_attestation = dict(operator)
    operator_without_attestation.pop("attestation", None)
    if operator_without_attestation != expected_operator:
        errors.append("operator configuration attestation mismatch")
    if not isinstance(operator_attestation, dict):
        errors.append("operator attestation reference is missing")
    else:
        attestation_path = repository_file(
            root,
            operator_attestation.get("path"),
            "operator attestation",
            errors,
        )
        if (
            attestation_path is not None
            and operator_attestation.get("sha256")
            != sha256_file(attestation_path)
        ):
            errors.append("operator attestation SHA-256 mismatch")

    supplemental = status.get("supplemental_evidence")
    if not isinstance(supplemental, dict):
        errors.append("load status requires supplemental evidence")
        supplemental = {}

    backpressure = supplemental.get("backpressure")
    if not isinstance(backpressure, dict):
        errors.append("load status requires backpressure evidence")
        backpressure = {}
    backpressure_path = repository_file(
        root, backpressure.get("path"), "backpressure evidence", errors
    )
    if backpressure_path is not None:
        if backpressure.get("sha256") != sha256_file(backpressure_path):
            errors.append("backpressure evidence SHA-256 mismatch")
        for error in nested_validator(
            "validate_p3b_backpressure_evidence.py",
            root,
            backpressure_path.relative_to(root),
        ):
            errors.append(f"backpressure evidence: {error}")

    analyzer = supplemental.get("independent_analyzer_low_rate")
    if not isinstance(analyzer, dict):
        errors.append("load status requires low-rate analyzer evidence")
        analyzer = {}
    analyzer_path = repository_file(
        root, analyzer.get("path"), "low-rate analyzer evidence", errors
    )
    if analyzer_path is not None:
        if analyzer.get("sha256") != sha256_file(analyzer_path):
            errors.append("low-rate analyzer evidence SHA-256 mismatch")
        for error in nested_validator(
            "validate_p3b_analyzer_evidence.py",
            root,
            analyzer_path.relative_to(root),
        ):
            errors.append(f"low-rate analyzer evidence: {error}")

    hotplug = supplemental.get("physical_usb_hotplug")
    if not isinstance(hotplug, dict):
        errors.append("load status requires physical USB hotplug evidence")
        hotplug = {}
    hotplug_path = repository_file(
        root, hotplug.get("path"), "physical USB hotplug evidence", errors
    )
    if hotplug_path is not None:
        if hotplug.get("sha256") != sha256_file(hotplug_path):
            errors.append("physical USB hotplug evidence SHA-256 mismatch")
        hotplug_value = read_json_file(
            hotplug_path, "physical USB hotplug evidence", errors
        )
        if hotplug_value.get("status") != "PASS":
            errors.append("physical USB hotplug status must be PASS")
        if hotplug_value.get("disconnect_method") != "physical-cable":
            errors.append("physical USB hotplug must use a physical cable")
        if (
            hotplug_value.get("required_cycles") != 1
            or hotplug_value.get("completed_cycles") != 1
        ):
            errors.append("physical USB hotplug evidence must bind exactly one cycle")
        if hotplug_value.get("initial_smoke", {}).get("exit_code") != 0:
            errors.append("physical USB hotplug initial smoke failed")
        cycles = hotplug_value.get("cycles")
        if (
            not isinstance(cycles, list)
            or len(cycles) != 1
            or cycles[0].get("recovery_smoke", {}).get("exit_code") != 0
        ):
            errors.append("physical USB hotplug recovery smoke failed")
        boundary_text = json.dumps(
            hotplug_value.get("evidence_boundary", {}), sort_keys=True
        )
        if "100 physical" in boundary_text or "100-cycle" in boundary_text:
            errors.append("physical USB hotplug evidence retains stale 100-cycle scope")

    readiness = supplemental.get("bus_off_fault_injection_readiness")
    if not isinstance(readiness, dict):
        errors.append("load status requires authoritative bus-off readiness evidence")
        readiness = {}
    readiness_path = repository_file(
        root, readiness.get("path"), "bus-off readiness evidence", errors
    )
    if readiness_path is not None:
        if readiness.get("sha256") != sha256_file(readiness_path):
            errors.append("bus-off readiness evidence SHA-256 mismatch")
        for error in nested_validator(
            "validate_p3b_bus_off_evidence.py",
            root,
            readiness_path.relative_to(root),
        ):
            errors.append(f"bus-off readiness evidence: {error}")

    attempt = supplemental.get("bus_off_attempt")
    if not isinstance(attempt, dict):
        errors.append("load status requires bus-off attempt evidence")
        attempt = {}
    attempt_path = repository_file(
        root, attempt.get("path"), "bus-off attempt evidence", errors
    )
    if attempt_path is not None:
        if attempt.get("sha256") != sha256_file(attempt_path):
            errors.append("bus-off attempt evidence SHA-256 mismatch")
        for error in nested_validator(
            "validate_p3b_bus_off_attempt.py",
            root,
            attempt_path.relative_to(root),
        ):
            errors.append(f"bus-off attempt evidence: {error}")

    blocker = supplemental.get("historical_bus_off_fault_injection_blocker")
    if not isinstance(blocker, dict):
        errors.append("load status requires historical bus-off blocker evidence")
        blocker = {}
    blocker_path = repository_file(
        root, blocker.get("path"), "historical bus-off blocker evidence", errors
    )
    if blocker_path is not None:
        if blocker.get("sha256") != sha256_file(blocker_path):
            errors.append("historical bus-off blocker evidence SHA-256 mismatch")
        blocker_value = read_json_file(
            blocker_path, "historical bus-off blocker evidence", errors
        )
        blocker_boundary = blocker_value.get("evidence_boundary")
        if (
            blocker_value.get("schema") != 1
            or blocker_value.get("phase") != "P3B"
            or blocker_value.get("test") != "bus-off/manual fault injection"
            or not isinstance(blocker_boundary, dict)
            or blocker_boundary.get("status") != "BLOCKED_BY_MISSING_TEST_HOOK"
        ):
            errors.append("historical bus-off blocker evidence mismatch")
        findings = blocker_value.get("findings")
        if not isinstance(findings, list) or len(findings) < 8:
            errors.append("historical bus-off blocker findings are incomplete")
        else:
            for finding in findings:
                if not isinstance(finding, dict):
                    errors.append("historical bus-off blocker finding is invalid")
                    continue
                if (
                    not isinstance(finding.get("path"), str)
                    or not isinstance(finding.get("sha256"), str)
                    or len(finding["sha256"]) != 64
                ):
                    errors.append(
                        "historical bus-off blocker finding reference is invalid"
                    )

    boundary = status.get("evidence_boundary")
    if not isinstance(boundary, dict):
        errors.append("load evidence boundary is missing")
        boundary = {}
    if boundary.get("statement") != EXPECTED_STATEMENT:
        errors.append("load evidence statement mismatch")
    pending = boundary.get("pending") if isinstance(boundary, dict) else None
    if pending != EXPECTED_PENDING:
        errors.append("load evidence pending set mismatch")
    completed = boundary.get("completed") if isinstance(boundary, dict) else None
    if completed != EXPECTED_COMPLETED:
        errors.append("load evidence completed set mismatch")
    limitations = boundary.get("limitations") if isinstance(boundary, dict) else None
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "6000 frame/s" in item for item in limitations
    ):
        errors.append("load evidence must record the 6000 frame/s analyzer limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "1 ms resolution" in item for item in limitations
    ):
        errors.append("load evidence must record the analyzer timestamp limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "sample point" in item for item in limitations
    ):
        errors.append("load evidence must record the detailed bit-timing limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str)
        and "90159" in item
        and "cannot exactly attribute" in item
        for item in limitations
    ):
        errors.append("load evidence must record the channel attribution limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str)
        and "TEC 128" in item
        and "no active fault injector" in item
        and "bus-off was not achieved" in item
        for item in limitations
    ):
        errors.append("load evidence must record the non-PASS bus-off attempt limitation")
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
    print("PASS P3B host/device load gate passed; qualification remains PARTIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
