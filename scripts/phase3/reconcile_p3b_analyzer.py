#!/usr/bin/env python3
"""Reconcile a low-rate independent CAN analyzer log with DUT capture evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIR = (
    ROOT
    / "artifacts/hil-2026-08-15/T-CAN-1M-1MS-ANALYZER-RECON-123111"
)
ANALYZER_LINE = re.compile(
    r"^(?P<date>\d{2}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<direction>Send|Recv)\[(?P<identifier>[0-9A-Fa-f]+)\]:"
    r"(?P<payload>(?:\s+[0-9A-Fa-f]{2})*)\s*$"
)
LOCAL_TIMEZONE = timezone(timedelta(hours=8))


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def iso_local(timestamp_ns: int) -> str:
    return datetime.fromtimestamp(
        timestamp_ns / 1_000_000_000, LOCAL_TIMEZONE
    ).isoformat(timespec="microseconds")


def parse_analyzer_log(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return records, [f"unable to read analyzer log: {exc}"]
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        match = ANALYZER_LINE.fullmatch(line)
        if match is None:
            errors.append(f"invalid analyzer log line {line_number}")
            continue
        parsed = datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%y-%m-%d %H:%M:%S.%f",
        ).replace(tzinfo=LOCAL_TIMEZONE)
        payload_text = match.group("payload").strip()
        payload = bytes.fromhex(payload_text) if payload_text else b""
        whole_seconds = int(parsed.replace(microsecond=0).timestamp())
        records.append(
            {
                "timestamp_ns": whole_seconds * 1_000_000_000
                + parsed.microsecond * 1_000,
                "timestamp_local": parsed.isoformat(timespec="milliseconds"),
                "direction": match.group("direction"),
                "arbitration_id": int(match.group("identifier"), 16),
                "payload_hex": payload.hex().upper(),
                "dlc": len(payload),
            }
        )
    return records, errors


def parse_frames(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    frames: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with path.open(newline="", encoding="ascii") as stream:
            reader = csv.DictReader(stream)
            expected = [
                "host_ingest_ns",
                "device_tick",
                "channel_sequence",
                "arbitration_id",
                "flags",
                "dlc",
                "device_drop_total",
                "event_sequence",
                "payload_hex",
            ]
            if reader.fieldnames != expected:
                return frames, ["unexpected frames.csv header"]
            for line_number, row in enumerate(reader, start=2):
                try:
                    frames.append(
                        {
                            "host_ingest_ns": int(row["host_ingest_ns"]),
                            "channel_sequence": int(row["channel_sequence"]),
                            "arbitration_id": int(row["arbitration_id"]),
                            "dlc": int(row["dlc"]),
                            "device_drop_total": int(row["device_drop_total"]),
                            "event_sequence": int(row["event_sequence"]),
                            "payload_hex": row["payload_hex"].upper(),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    errors.append(f"invalid frames.csv row {line_number}")
    except OSError as exc:
        errors.append(f"unable to read frames.csv: {exc}")
    return frames, errors


def measurement_window(path: Path) -> tuple[int, int, list[str]]:
    errors: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    try:
        with path.open(newline="", encoding="ascii") as stream:
            for row in csv.DictReader(stream):
                if row.get("phase") == "measurement_start":
                    starts.append(int(row["host_poll_ns"]))
                elif row.get("phase") == "measurement_end":
                    ends.append(int(row["host_poll_ns"]))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return 0, 0, [f"unable to read measurement window: {exc}"]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        errors.append("diagnostics require exactly one valid measurement window")
        return 0, 0, errors
    return starts[0], ends[0], errors


def affine_fit_residuals(
    dut_timestamps: list[int], analyzer_timestamps: list[int]
) -> tuple[float, list[float]]:
    if len(dut_timestamps) < 2 or len(dut_timestamps) != len(analyzer_timestamps):
        return 0.0, []
    x0 = dut_timestamps[0]
    y0 = analyzer_timestamps[0]
    xs = [(value - x0) / 1_000_000.0 for value in dut_timestamps]
    ys = [(value - y0) / 1_000_000.0 for value in analyzer_timestamps]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((value - mean_x) ** 2 for value in xs)
    if variance == 0:
        return 0.0, []
    slope = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    ) / variance
    intercept = mean_y - slope * mean_x
    residuals = [
        abs(y - (intercept + slope * x))
        for x, y in zip(xs, ys, strict=True)
    ]
    return slope, residuals


def reconcile(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "errors": [f"unable to read summary.json: {exc}"]}
    if not isinstance(summary, dict):
        return {"status": "FAIL", "errors": ["summary.json root must be an object"]}

    analyzer, analyzer_errors = parse_analyzer_log(run_dir / "analyzer-log.txt")
    frames, frame_errors = parse_frames(run_dir / "frames.csv")
    start_ns, end_ns, window_errors = measurement_window(
        run_dir / "diagnostics.csv"
    )
    errors = analyzer_errors + frame_errors + window_errors

    pre_window_count = sum(
        record["timestamp_ns"] < start_ns for record in analyzer
    )
    post_window_count = sum(
        record["timestamp_ns"] > end_ns for record in analyzer
    )

    if not analyzer:
        errors.append("analyzer log contains no records")
    if not frames:
        errors.append("frames.csv contains no records")
    if summary.get("frames") != len(frames):
        errors.append("summary frame count does not match frames.csv")
    dut_timestamps = [frame["host_ingest_ns"] for frame in frames]
    aligned = (
        [
            record
            for record in analyzer
            if dut_timestamps[0]
            <= record["timestamp_ns"]
            <= dut_timestamps[-1]
        ]
        if dut_timestamps
        else []
    )
    if len(aligned) != len(frames):
        errors.append("DUT active-span analyzer count does not match DUT frames")
    if any(
        analyzer[index]["timestamp_ns"] <= analyzer[index - 1]["timestamp_ns"]
        for index in range(1, len(analyzer))
    ):
        errors.append("analyzer timestamps are not strictly increasing")
    if any(record["direction"] != "Send" for record in analyzer):
        errors.append("analyzer log contains records other than Send")

    compared = min(len(aligned), len(frames))
    id_mismatches = 0
    dlc_mismatches = 0
    payload_mismatches = 0
    for analyzer_record, dut_frame in zip(
        aligned[:compared], frames[:compared], strict=True
    ):
        if analyzer_record["arbitration_id"] != dut_frame["arbitration_id"]:
            id_mismatches += 1
        if analyzer_record["dlc"] != dut_frame["dlc"]:
            dlc_mismatches += 1
        if analyzer_record["payload_hex"] != dut_frame["payload_hex"]:
            payload_mismatches += 1
    if id_mismatches:
        errors.append("analyzer/DUT arbitration ID mismatch")
    if dlc_mismatches:
        errors.append("analyzer/DUT DLC mismatch")
    if payload_mismatches:
        errors.append("analyzer/DUT payload mismatch")

    for name in (
        "event_gaps",
        "channel_gaps",
        "forward_missing_records",
        "backward_or_duplicate_records",
        "device_drop_total",
        "measurement_queue_drops",
        "measurement_ring_drops",
        "data_loss_events",
        "data_loss_dropped",
    ):
        if summary.get(name) != 0:
            errors.append(f"low-rate DUT run reports nonzero {name}")

    analyzer_timestamps = [record["timestamp_ns"] for record in aligned]
    analyzer_span_seconds = (
        (analyzer_timestamps[-1] - analyzer_timestamps[0]) / 1_000_000_000
        if len(analyzer_timestamps) >= 2
        else 0.0
    )
    dut_span_seconds = (
        (dut_timestamps[-1] - dut_timestamps[0]) / 1_000_000_000
        if len(dut_timestamps) >= 2
        else 0.0
    )
    analyzer_rate = (
        (len(analyzer_timestamps) - 1) / analyzer_span_seconds
        if analyzer_span_seconds > 0
        else 0.0
    )
    dut_rate = (
        (len(dut_timestamps) - 1) / dut_span_seconds
        if dut_span_seconds > 0
        else 0.0
    )
    rate_difference_percent = (
        abs(analyzer_rate - dut_rate) / dut_rate * 100 if dut_rate > 0 else 0.0
    )
    if rate_difference_percent > 0.5:
        errors.append("analyzer/DUT active-span rates differ by more than 0.5 percent")

    analyzer_intervals_ms = [
        (analyzer_timestamps[index] - analyzer_timestamps[index - 1])
        / 1_000_000.0
        for index in range(1, len(analyzer_timestamps))
    ]
    dut_intervals_ms = [
        (dut_timestamps[index] - dut_timestamps[index - 1]) / 1_000_000.0
        for index in range(1, len(dut_timestamps))
    ]
    interval_errors_ms = [
        abs(analyzer_value - dut_value)
        for analyzer_value, dut_value in zip(analyzer_intervals_ms, dut_intervals_ms)
    ]
    affine_slope, affine_residuals_ms = affine_fit_residuals(
        dut_timestamps, analyzer_timestamps
    )

    exact_match = (
        bool(frames)
        and len(aligned) == len(frames)
        and id_mismatches == 0
        and dlc_mismatches == 0
        and payload_mismatches == 0
    )
    if pre_window_count == 0 or post_window_count == 0:
        errors.append("analyzer log does not bracket the DUT measurement window")

    return {
        "schema": 1,
        "status": "PASS_WITH_LIMITATION" if not errors else "FAIL",
        "frame_reconciliation": "PASS" if exact_match and not errors else "FAIL",
        "record_order_reconciliation": (
            "NOT_DISTINGUISHABLE_IDENTICAL_FRAMES"
            if exact_match and not errors
            else "FAIL"
        ),
        "timestamp_reconciliation": (
            "PASS_WITH_LIMITATION" if exact_match and not errors else "FAIL"
        ),
        "high_rate_analyzer_coverage": False,
        "analyzer_timestamp_resolution_ms": 1,
        "analyzer_timezone": "UTC+08:00",
        "analyzer_total_records": len(analyzer),
        "analyzer_pre_window_records": pre_window_count,
        "analyzer_measurement_records": len(aligned),
        "analyzer_post_window_records": post_window_count,
        "dut_frame_records": len(frames),
        "compared_records": compared,
        "id_mismatches": id_mismatches,
        "dlc_mismatches": dlc_mismatches,
        "payload_mismatches": payload_mismatches,
        "measurement_start_local": iso_local(start_ns) if start_ns else None,
        "measurement_end_local": iso_local(end_ns) if end_ns else None,
        "analyzer_first_aligned_local": (
            aligned[0]["timestamp_local"] if aligned else None
        ),
        "analyzer_last_aligned_local": (
            aligned[-1]["timestamp_local"] if aligned else None
        ),
        "dut_first_frame_local": (
            iso_local(dut_timestamps[0]) if dut_timestamps else None
        ),
        "dut_last_frame_local": (
            iso_local(dut_timestamps[-1]) if dut_timestamps else None
        ),
        "first_endpoint_offset_ms": (
            (analyzer_timestamps[0] - dut_timestamps[0]) / 1_000_000.0
            if analyzer_timestamps and dut_timestamps
            else None
        ),
        "last_endpoint_offset_ms": (
            (analyzer_timestamps[-1] - dut_timestamps[-1]) / 1_000_000.0
            if analyzer_timestamps and dut_timestamps
            else None
        ),
        "analyzer_active_span_seconds": analyzer_span_seconds,
        "dut_active_span_seconds": dut_span_seconds,
        "analyzer_frames_per_second_over_active_span": analyzer_rate,
        "dut_frames_per_second_over_active_span": dut_rate,
        "active_span_rate_difference_percent": rate_difference_percent,
        "interval_error_ms_p50": percentile(interval_errors_ms, 0.50),
        "interval_error_ms_p95": percentile(interval_errors_ms, 0.95),
        "interval_error_ms_p99": percentile(interval_errors_ms, 0.99),
        "affine_slope_analyzer_per_dut": affine_slope,
        "affine_fit_residual_ms_p95": percentile(affine_residuals_ms, 0.95),
        "dut_summary": {
            name: summary.get(name)
            for name in (
                "warmup_seconds",
                "duration_seconds",
                "frames",
                "frames_per_second",
                "event_gaps",
                "channel_gaps",
                "forward_missing_records",
                "device_drop_total",
                "measurement_queue_drops",
                "measurement_ring_drops",
                "latency_ns_p95",
                "fit_residual_ns_p95",
                "host_acceptance",
            )
        },
        "limitations": [
            "Every observed frame has the same 0x7FF identifier, DLC 0, and empty payload, so independent record-order permutations are not distinguishable even though counts and per-position content match.",
            "The analyzer timestamp text has 1 ms resolution and exhibits logger/scheduler jitter; sub-millisecond timestamp accuracy is not claimed.",
            "This approximately 64 frame/s export-capable window does not provide independent analyzer timestamp coverage for the separate 6000 frame/s qualification run.",
        ],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        help="Defaults to <run-dir>/analyzer-reconciliation.json",
    )
    args = parser.parse_args()
    output = args.output or args.run_dir / "analyzer-reconciliation.json"
    result = reconcile(args.run_dir)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"{result['status']} frames={result.get('dut_frame_records', 0)} "
        f"analyzer={result.get('analyzer_measurement_records', 0)} "
        f"output={output}"
    )
    return 0 if result["status"] == "PASS_WITH_LIMITATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
