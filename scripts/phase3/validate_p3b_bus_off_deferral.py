#!/usr/bin/env python3
"""Validate the P3B active bus-off HIL deferral boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEFERRAL = Path(
    "docs/evidence/phase3/P3B-bus-off-deferral-2026-08-17.json"
)

EXPECTED_HEADER = {
    "schema": 1,
    "phase": "P3B",
    "recorded_on": "2026-08-17",
    "decision": "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
    "hardware_bus_off_status": "NOT_COMPLETED",
    "qualification_status": "PARTIAL",
    "p4e_qualification_gate": "BLOCKED",
    "freeze_ready": False,
    "hardware_execution_authorized": False,
    "development_continuation": "AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE",
}
EXPECTED_LAST_ATTEMPT = {
    "outcome": "TIMEOUT_CLEANED_NOT_BUS_OFF",
    "warning_observed": 1,
    "error_passive_observed": 1,
    "max_tec": 128,
    "bus_off_observed": 0,
    "final_psr_bo": 0,
}
EXPECTED_AUTHORIZED_SCOPE = [
    "non-bus-off firmware functionality",
    "USB and protocol integration",
    "host core and CLI development",
    "single-channel E2E implementation excluding bus-off qualification closure",
    "dual-channel implementation and non-bus-off reliability work",
]
EXPECTED_PROHIBITED_CLAIMS = [
    "P3B PASS",
    "P4E qualification complete",
    "hardware bus-off verified",
    "freeze ready",
    "release qualification complete",
]
EXPECTED_PROHIBITED_SUBSTITUTIONS = [
    "GDB writes to result state, latch, PSR, or ECR",
    "silent or no-ACK operation alone",
    "intentional bitrate mismatch",
    "intentional termination or wiring misuse",
]
EXPECTED_RESUME_CONDITIONS = [
    "a qualified active CAN fault injector or independently qualified equivalent device is available",
    "injector identity, supported error types, electrical limits, and emergency stop conditions are recorded",
    "bus bitrate, sample point, mode, termination, common ground, and idle voltage preflight is complete",
    "three independent run IDs, nonces, evidence paths, and reset boundaries are assigned",
    "raw GDB transcript and analyzer capture capability is confirmed",
    "a new explicit hardware execution authorization is obtained",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    root: Path, deferral_path: Path = DEFAULT_DEFERRAL
) -> list[str]:
    errors: list[str] = []
    path = repository_file(root, deferral_path.as_posix(), "P3B deferral", errors)
    if path is None:
        return errors
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid P3B deferral: {exc}"]
    if not isinstance(value, dict):
        return ["P3B deferral root must be an object"]

    for name, expected in EXPECTED_HEADER.items():
        if value.get(name) != expected:
            errors.append(f"P3B deferral mismatch: {name}")
    if value.get("last_hardware_attempt") != EXPECTED_LAST_ATTEMPT:
        errors.append("P3B deferral last-attempt boundary mismatch")
    for name, expected in (
        ("authorized_scope", EXPECTED_AUTHORIZED_SCOPE),
        ("prohibited_claims", EXPECTED_PROHIBITED_CLAIMS),
        ("prohibited_substitutions", EXPECTED_PROHIBITED_SUBSTITUTIONS),
        ("resume_conditions", EXPECTED_RESUME_CONDITIONS),
    ):
        if value.get(name) != expected:
            errors.append(f"P3B deferral policy mismatch: {name}")

    references = value.get("authoritative_references")
    if not isinstance(references, dict):
        errors.append("P3B deferral authoritative references are missing")
        references = {}
    for name in ("last_attempt", "readiness", "blocked_preflight"):
        reference = references.get(name)
        if not isinstance(reference, dict):
            errors.append(f"missing P3B deferral reference: {name}")
            continue
        target = repository_file(root, reference.get("path"), name, errors)
        digest = reference.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"invalid P3B deferral reference SHA-256: {name}")
        elif target is not None and sha256_file(target) != digest:
            errors.append(f"P3B deferral reference SHA-256 mismatch: {name}")

    blocker = value.get("historical_blocker")
    if not isinstance(blocker, dict):
        errors.append("P3B historical blocker reference is missing")
    else:
        if (
            blocker.get("authority") != "HISTORICAL_ONLY"
            or blocker.get("preserve_original") is not True
        ):
            errors.append("P3B historical blocker boundary mismatch")
        target = repository_file(
            root, blocker.get("path"), "historical blocker", errors
        )
        if target is not None and sha256_file(target) != blocker.get("sha256"):
            errors.append("P3B historical blocker SHA-256 mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--deferral", type=Path, default=DEFAULT_DEFERRAL)
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.deferral)
    if errors:
        raise SystemExit("; ".join(errors))
    print("PASS P3B bus-off decision=DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY")


if __name__ == "__main__":
    main()
