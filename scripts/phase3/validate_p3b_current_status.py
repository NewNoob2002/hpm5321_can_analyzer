#!/usr/bin/env python3
"""Validate the stable P3B status entry and external evidence index."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS = Path("docs/evidence/phase3/P3B-current-status.json")
EXPECTED_RETENTION = "project_lifetime_plus_2_years"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_file(root: Path, value: object, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"invalid {label}")
        return None
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
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


def validate(root: Path, status_path: Path = DEFAULT_STATUS) -> list[str]:
    errors: list[str] = []
    path = repository_file(root, status_path.as_posix(), "P3B current status", errors)
    if path is None:
        return errors
    try:
        status = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid P3B current status: {exc}"]
    expected = {
        "schema": 1,
        "phase": "P3B",
        "qualification_status": "PARTIAL",
        "p4e_gate": "BLOCKED",
        "load_gate": "PASS_HOST_LOAD_ACCEPTANCE",
        "bus_off_gate": "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
        "bus_off_last_attempt": "TIMEOUT_CLEANED_NOT_BUS_OFF",
        "development_continuation": "AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE",
        "freeze_status": "BLOCKED",
    }
    for name, value in expected.items():
        if status.get(name) != value:
            errors.append(f"P3B current status mismatch: {name}")
    if not isinstance(status.get("freeze_blockers"), list) or not status["freeze_blockers"]:
        errors.append("P3B current status requires freeze blockers")

    references = status.get("authoritative_evidence")
    if not isinstance(references, dict):
        errors.append("P3B current status requires authoritative evidence")
        references = {}
    for name in (
        "load_status",
        "bus_off_readiness",
        "bus_off_attempt",
        "bus_off_deferral",
    ):
        reference = references.get(name)
        if not isinstance(reference, dict):
            errors.append(f"missing authoritative evidence: {name}")
            continue
        target = repository_file(root, reference.get("path"), name, errors)
        digest = reference.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"invalid authoritative evidence SHA-256: {name}")
        elif target is not None and sha256_file(target) != digest:
            errors.append(f"authoritative evidence SHA-256 mismatch: {name}")

    blocker = status.get("historical_blocker")
    if not isinstance(blocker, dict):
        errors.append("historical blocker reference is missing")
    else:
        if blocker.get("authority") != "HISTORICAL_ONLY" or blocker.get("preserve_original") is not True:
            errors.append("historical blocker must remain preserved and non-authoritative")
        target = repository_file(root, blocker.get("path"), "historical blocker", errors)
        if target is not None and sha256_file(target) != blocker.get("sha256"):
            errors.append("historical blocker SHA-256 mismatch")

    index_path = repository_file(root, status.get("external_artifact_index"), "external artifact index", errors)
    if index_path is not None:
        index = json.loads(index_path.read_text())
        if index.get("schema") != 1 or index.get("retention") != EXPECTED_RETENTION:
            errors.append("external artifact index policy mismatch")
        artifacts = index.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            errors.append("external artifact index requires artifacts")
        else:
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    errors.append("invalid external artifact record")
                    continue
                if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256", ""))):
                    errors.append("external artifact SHA-256 is invalid")
                if not isinstance(artifact.get("size"), int) or artifact["size"] <= 5 * 1024 * 1024:
                    errors.append("external artifact size must exceed repository threshold")
                if not isinstance(artifact.get("members"), list) or not artifact["members"]:
                    errors.append("external artifact member table is missing")
                if not isinstance(artifact.get("key_excerpt"), dict) or not artifact["key_excerpt"]:
                    errors.append("external artifact key excerpt is missing")
                if artifact.get("archive_status") == "ARCHIVED":
                    if not artifact.get("immutable_object_id") or not artifact.get("location"):
                        errors.append("archived external artifact lacks immutable identity")
            freeze_ready = all(
                item.get("archive_status") == "ARCHIVED"
                and item.get("immutable_object_id")
                and item.get("location")
                for item in artifacts if isinstance(item, dict)
            )
            if index.get("freeze_ready") is not freeze_ready:
                errors.append("external artifact freeze readiness mismatch")
            if freeze_ready and status.get("freeze_status") != "READY":
                errors.append("P3B freeze status was not updated after archive completion")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.status)
    if errors:
        raise SystemExit("; ".join(errors))
    print(f"PASS P3B current status={args.status}")


if __name__ == "__main__":
    main()
