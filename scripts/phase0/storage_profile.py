#!/usr/bin/env python3
"""Calculate and validate the P0S storage-profile closure evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = Path("docs/approved-plan/profiles/bp-storage-v1.md")
REQUIRED_CAPACITIES_GB = (4, 8, 16, 32)


def queue_absorption_ms(
    encoded_capture_bytes_per_s: float,
    io_block_bytes: int = 4096,
    queue_depth: int = 8,
) -> float:
    if encoded_capture_bytes_per_s <= 0:
        raise ValueError("encoded capture rate must be positive")
    if io_block_bytes <= 0 or queue_depth <= 0:
        raise ValueError("queue geometry must be positive")
    return io_block_bytes * queue_depth / encoded_capture_bytes_per_s * 1000.0


def _profile_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if match and match.group(1) not in {"Key", "---"}:
            rows[match.group(1).strip()] = match.group(2).strip()
    return rows


def _positive_number(value: Any, field: str, errors: list[str]) -> float | None:
    if isinstance(value, bool):
        errors.append(f"{field} must be positive numeric")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be positive numeric")
        return None
    if not math.isfinite(number) or number <= 0:
        errors.append(f"{field} must be positive numeric")
        return None
    return number


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read evidence {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("evidence root must be an object")
        return {}
    return value


def validate(root: Path, evidence_path: Path) -> list[str]:
    errors: list[str] = []
    evidence = _load_json(evidence_path, errors)
    if not evidence:
        return errors

    if evidence.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if evidence.get("status") != "PASS":
        errors.append("P0S evidence status must be PASS")

    workload = evidence.get("workload", {})
    if not isinstance(workload, dict):
        workload = {}
    if workload.get("profile") != "BP-CAN-BETA-v1":
        errors.append("workload profile must be BP-CAN-BETA-v1")
    if workload.get("status") != "FROZEN":
        errors.append("BP-CAN-BETA-v1 must be FROZEN")
    encoded_rate = _positive_number(
        workload.get("encoded_capture_bytes_per_s"),
        "workload.encoded_capture_bytes_per_s",
        errors,
    )

    electrical = evidence.get("electrical", {})
    if not isinstance(electrical, dict):
        electrical = {}
    if not str(electrical.get("schematic_or_bom_ref", "")).strip():
        errors.append("electrical.schematic_or_bom_ref is required")
    if electrical.get("cs_active_level") not in (0, 1):
        errors.append("electrical.cs_active_level must be 0 or 1")
    present = electrical.get("detect_present_level")
    absent = electrical.get("detect_absent_level")
    if present not in (0, 1) or absent not in (0, 1) or present == absent:
        errors.append("detect present/absent levels must be distinct binary values")
    if str(electrical.get("detect_pull", "")).upper() in {"", "UNKNOWN", "TBD"}:
        errors.append("electrical.detect_pull must be proven")
    _positive_number(electrical.get("debounce_ms"), "electrical.debounce_ms", errors)

    media = evidence.get("media", [])
    if not isinstance(media, list):
        media = []
    vendors_by_capacity: dict[int, set[str]] = {
        capacity: set() for capacity in REQUIRED_CAPACITIES_GB
    }
    for index, item in enumerate(media):
        if not isinstance(item, dict):
            errors.append(f"media[{index}] must be an object")
            continue
        capacity = item.get("marketed_capacity_gb")
        vendor = str(item.get("vendor", "")).strip()
        valid = (
            capacity in REQUIRED_CAPACITIES_GB
            and vendor
            and item.get("filesystem") == "FAT32"
            and item.get("logical_sector_bytes") == 512
            and item.get("status") == "PASS"
        )
        if not valid:
            errors.append(f"media[{index}] does not satisfy the SDHC/FAT32 contract")
            continue
        vendors_by_capacity[int(capacity)].add(vendor.casefold())
    for capacity, vendors in vendors_by_capacity.items():
        if len(vendors) < 2:
            errors.append(f"media matrix needs two vendors at {capacity} GB")

    profile_path = root / PROFILE_PATH
    try:
        rows = _profile_rows(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {PROFILE_PATH}: {exc}")
        return errors
    if rows.get("status") != "FROZEN":
        errors.append("BP-STORAGE-v1 status must be FROZEN")

    profile_rate = _positive_number(
        rows.get("encoded_capture_bytes_per_s"),
        "profile.encoded_capture_bytes_per_s",
        errors,
    )
    profile_absorption = _positive_number(
        rows.get("queue_absorption_ms"), "profile.queue_absorption_ms", errors
    )
    deadline = _positive_number(
        rows.get("operation_deadline_ms"), "profile.operation_deadline_ms", errors
    )
    try:
        io_block_bytes = int(rows.get("io_block_bytes", ""))
        queue_depth = int(rows.get("queue_depth", ""))
    except ValueError:
        errors.append("profile queue geometry must be integral")
        io_block_bytes = 0
        queue_depth = 0

    if encoded_rate is not None and profile_rate is not None and not math.isclose(
        encoded_rate, profile_rate, rel_tol=1e-9
    ):
        errors.append("evidence encoded rate does not match BP-STORAGE-v1")
    if profile_rate is not None and io_block_bytes > 0 and queue_depth > 0:
        calculated = queue_absorption_ms(profile_rate, io_block_bytes, queue_depth)
        if profile_absorption is not None and not math.isclose(
            calculated, profile_absorption, rel_tol=1e-6, abs_tol=0.001
        ):
            errors.append(
                "profile queue_absorption_ms does not match queue capacity / encoded rate"
            )
        if deadline is not None and deadline > calculated * 0.5:
            errors.append("profile operation deadline exceeds 50% of queue absorption")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    calculate = subparsers.add_parser("calculate")
    calculate.add_argument("--encoded-rate", type=float, required=True)
    calculate.add_argument("--io-block-bytes", type=int, default=4096)
    calculate.add_argument("--queue-depth", type=int, default=8)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    validate_parser.add_argument("--evidence", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "calculate":
        try:
            absorption = queue_absorption_ms(
                args.encoded_rate, args.io_block_bytes, args.queue_depth
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    "encoded_capture_bytes_per_s": args.encoded_rate,
                    "queue_capacity_bytes": args.io_block_bytes * args.queue_depth,
                    "queue_absorption_ms": round(absorption, 6),
                    "operation_deadline_ceiling_ms": round(absorption * 0.5, 6),
                    "p99_sync_ceiling_ms": round(absorption * 0.25, 6),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    errors = validate(args.root.resolve(), args.evidence.resolve())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS P0S storage evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
