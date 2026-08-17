#!/usr/bin/env python3
"""Validate the post-P3B-deferral system work-plan boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = Path("docs/development/p3b-next-step-work-plan.md")
DEFAULT_STATUS = Path("docs/evidence/phase3/P3B-current-status.json")

EXPECTED_STATUS = {
    "qualification_status": "PARTIAL",
    "p4e_gate": "BLOCKED",
    "bus_off_gate": "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
    "development_continuation": "AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE",
    "freeze_status": "BLOCKED",
}

REQUIRED_MARKERS = (
    "P3B=PARTIAL",
    "P4E=BLOCKED",
    "freeze_ready=false",
    "hardware_bus_off=NOT_COMPLETED",
    "hardware_execution_authorized=false",
    "bus_off_gate=DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
    "development_continuation=AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE",
    "single_channel_before_dual_channel=true",
)

ORDERED_WORK_PACKAGES = (
    "## 3. WP0",
    "## 4. WP1",
    "## 5. WP2",
    "## 6. WP3",
    "## 7. WP4",
    "## 8. WP5",
    "## 9. Deferred lane",
)

REQUIRED_SCOPE_MARKERS = (
    "T-PROTO-001..012",
    "T-E2E-009",
    "T-FW-003",
    "qualified active CAN fault injector",
    "GDB 状态写入",
    "macOS 保持 deferred",
    "Qt/GUI 不进入当前依赖图",
    "STORAGE、UPDATE、GUI",
)

FORBIDDEN_CLAIMS = (
    "P3B=PASS",
    "P4E=PASS",
    "freeze_ready=true",
    "hardware_bus_off=PASS",
    "hardware_execution_authorized=true",
    "MVP=PASS",
    "Beta=PASS",
    "release=PASS",
)


def repository_file(
    root: Path, value: object, label: str, errors: list[str]
) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"invalid {label}")
        return None
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        errors.append(f"invalid {label}")
        return None
    path = root / value
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError):
        errors.append(f"missing {label}: {value}")
        return None
    if path.is_symlink() or not resolved.is_file():
        errors.append(f"{label} must be a regular repository file")
        return None
    return resolved


def validate(
    root: Path,
    plan_path: Path = DEFAULT_PLAN,
    status_path: Path = DEFAULT_STATUS,
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    plan = repository_file(root, plan_path.as_posix(), "next-step work plan", errors)
    status = repository_file(root, status_path.as_posix(), "P3B current status", errors)
    if plan is None or status is None:
        return errors

    try:
        text = plan.read_text(encoding="utf-8")
        value = json.loads(status.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid next-step work-plan input: {exc}"]
    if not isinstance(value, dict):
        return ["P3B current status root must be an object"]

    for name, expected in EXPECTED_STATUS.items():
        if value.get(name) != expected:
            errors.append(f"next-step plan status mismatch: {name}")

    for marker in REQUIRED_MARKERS:
        if text.count(marker) != 1:
            errors.append(f"next-step plan requires exactly one marker: {marker}")

    positions = []
    for heading in ORDERED_WORK_PACKAGES:
        position = text.find(heading)
        if position < 0:
            errors.append(f"next-step plan missing work package: {heading}")
        positions.append(position)
    present_positions = [position for position in positions if position >= 0]
    if present_positions != sorted(present_positions):
        errors.append("next-step plan work-package order mismatch")

    for marker in REQUIRED_SCOPE_MARKERS:
        if marker not in text:
            errors.append(f"next-step plan missing scope boundary: {marker}")

    for claim in FORBIDDEN_CLAIMS:
        if claim in text:
            errors.append(
                f"next-step plan contains forbidden qualification claim: {claim}"
            )

    single_channel = text.find("## 5. WP2")
    dual_channel = text.find("## 8. WP5")
    if single_channel < 0 or dual_channel < 0 or single_channel >= dual_channel:
        errors.append("next-step plan must sequence single-channel before dual-channel")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.plan, args.status)
    if errors:
        raise SystemExit("; ".join(errors))
    print("PASS P3B next-step work plan preserves deferred hardware gate")


if __name__ == "__main__":
    main()
