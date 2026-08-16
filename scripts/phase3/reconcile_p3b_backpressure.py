#!/usr/bin/env python3
"""Reconcile P3B USB-backpressure event loss against retained HIL evidence."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


EVENT_DATA_LOSS = 0x8005
EVENT_FLOW_CONTROL = 0x8004


def next_nonzero(value: int) -> int:
    value = (value + 1) & 0xFFFF_FFFF
    return value or 1


def previous_nonzero(value: int) -> int:
    return 0xFFFF_FFFF if value == 1 else value - 1


def split_nonzero_range(first: int, last: int) -> list[tuple[int, int]]:
    if not 1 <= first <= 0xFFFF_FFFF or not 1 <= last <= 0xFFFF_FFFF:
        raise ValueError("event sequences must be nonzero u32 values")
    if first <= last:
        return [(first, last)]
    return [(first, 0xFFFF_FFFF), (1, last)]


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for first, last in sorted(ranges):
        if not merged or first > merged[-1][1] + 1:
            merged.append([first, last])
        else:
            merged[-1][1] = max(merged[-1][1], last)
    return [(first, last) for first, last in merged]


def range_count(ranges: list[tuple[int, int]]) -> int:
    return sum(last - first + 1 for first, last in ranges)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def observed_missing_ranges(events: list[dict[str, str]]) -> tuple[list[tuple[int, int]], list[str]]:
    errors: list[str] = []
    missing: list[tuple[int, int]] = []
    previous = 0
    seen: set[int] = set()
    for index, row in enumerate(events, start=2):
        try:
            sequence = int(row["event_sequence"])
        except (KeyError, ValueError):
            errors.append(f"events.csv row {index} has invalid event_sequence")
            continue
        if not 1 <= sequence <= 0xFFFF_FFFF:
            errors.append(f"events.csv row {index} has out-of-range event_sequence")
            continue
        if sequence in seen:
            errors.append(f"events.csv repeats event_sequence {sequence}")
        seen.add(sequence)
        if previous:
            expected = next_nonzero(previous)
            if sequence != expected:
                distance = (sequence - expected) & 0xFFFF_FFFF
                if distance >= 0x8000_0000:
                    errors.append(
                        f"events.csv is non-monotonic at {previous}->{sequence}"
                    )
                else:
                    missing.extend(
                        split_nonzero_range(expected, previous_nonzero(sequence))
                    )
        previous = sequence
    return merge_ranges(missing), errors


def declared_loss_ranges(
    losses: list[dict[str, str]],
) -> tuple[list[tuple[int, int]], int, list[str]]:
    errors: list[str] = []
    ranges: list[tuple[int, int]] = []
    declared_count = 0
    for index, row in enumerate(losses, start=2):
        try:
            domain = int(row["sequence_domain"])
            first = int(row["first_dropped_sequence"])
            last = int(row["last_dropped_sequence"])
            dropped = int(row["dropped_count"])
        except (KeyError, ValueError):
            errors.append(f"data_loss.csv row {index} is invalid")
            continue
        if domain != 1:
            continue
        try:
            split = split_nonzero_range(first, last)
        except ValueError as exc:
            errors.append(f"data_loss.csv row {index}: {exc}")
            continue
        encoded_count = range_count(split)
        if dropped != encoded_count:
            errors.append(
                f"data_loss.csv row {index} count mismatch: {dropped}!={encoded_count}"
            )
        declared_count += dropped
        ranges.extend(split)
    merged = merge_ranges(ranges)
    if range_count(merged) != declared_count:
        errors.append("DATA_LOSS event-domain ranges overlap or duplicate sequences")
    return merged, declared_count, errors


def reconcile(run_dir: Path) -> dict[str, Any]:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = read_csv(run_dir / "events.csv")
    losses = read_csv(run_dir / "data_loss.csv")
    frames = read_csv(run_dir / "frames.csv")

    missing_ranges, errors = observed_missing_ranges(events)
    declared_ranges, declared_count, loss_errors = declared_loss_ranges(losses)
    errors.extend(loss_errors)

    event_types = Counter(int(row["message_type"]) for row in events)
    loss_event_sequences = {
        int(row["event_sequence"])
        for row in losses
        if int(row["sequence_domain"]) == 1
    }
    ledger_loss_sequences = {
        int(row["event_sequence"])
        for row in events
        if int(row["message_type"]) == EVENT_DATA_LOSS
    }
    if loss_event_sequences != ledger_loss_sequences:
        errors.append("DATA_LOSS rows do not match DATA_LOSS events in events.csv")

    event_exact = missing_ranges == declared_ranges and not errors
    last_loss_event = max(loss_event_sequences, default=0)
    recovered_frame_events = {
        int(row["event_sequence"])
        for row in frames
        if int(row["event_sequence"]) > last_loss_event
    }
    recovery = (
        bool(recovered_frame_events)
        and summary.get("device_drop_total") == 0
        and summary.get("measurement_queue_drops") == 0
        and summary.get("measurement_ring_drops") == 0
    )

    channel_missing = int(summary.get("forward_missing_records", 0))
    channel_domain_dropped = sum(
        int(row["dropped_count"])
        for row in losses
        if int(row["sequence_domain"]) == 2
    )
    if channel_missing == 0:
        channel_status = "PASS"
    elif channel_domain_dropped == channel_missing:
        channel_status = "PASS"
    else:
        channel_status = "PARTIAL"

    if event_exact and recovery and channel_status == "PASS":
        overall = "PASS"
    elif event_exact and recovery:
        overall = "PARTIAL"
    else:
        overall = "FAIL"

    return {
        "schema": 1,
        "test": "P3B CAN-load USB backpressure reconciliation",
        "status": overall,
        "usb_backpressure_recovery": "PASS" if recovery else "FAIL",
        "event_sequence_reconciliation": "PASS" if event_exact else "FAIL",
        "channel_sequence_reconciliation": channel_status,
        "observed_event_missing_ranges": [
            {"first": first, "last": last, "count": last - first + 1}
            for first, last in missing_ranges
        ],
        "declared_event_loss_ranges": [
            {"first": first, "last": last, "count": last - first + 1}
            for first, last in declared_ranges
        ],
        "observed_event_missing_count": range_count(missing_ranges),
        "declared_event_loss_count": declared_count,
        "data_loss_event_count": event_types[EVENT_DATA_LOSS],
        "flow_control_event_count": event_types[EVENT_FLOW_CONTROL],
        "channel_missing_records": channel_missing,
        "channel_domain_declared_drops": channel_domain_dropped,
        "post_loss_frame_event_count": len(recovered_frame_events),
        "limitations": (
            []
            if channel_status == "PASS"
            else [
                "DATA_LOSS is in the EVENT sequence domain, so the exact number "
                "of CAN records inside each dropped batch cannot be reconstructed."
            ]
        ),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = reconcile(args.run_dir)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
