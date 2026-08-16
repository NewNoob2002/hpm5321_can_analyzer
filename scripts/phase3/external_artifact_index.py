"""Fail-closed lookup for large P3B artifacts stored outside normal Git."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


INDEX_PATH = Path("docs/evidence/phase3/P3B-external-artifacts.json")
EXPECTED_RETENTION = "project_lifetime_plus_2_years"


def _safe_relative(value: object, label: str, errors: list[str]) -> str | None:
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


def validate_detached_reference(
    root: Path, reference: dict[str, Any], errors: list[str]
) -> dict[str, Any] | None:
    """Validate a missing package against the repository-resident external index."""
    package_path = _safe_relative(reference.get("path"), "detached package path", errors)
    if package_path is None:
        return None
    index_path = root / INDEX_PATH
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid external artifact index: {exc}")
        return None
    if index.get("schema") != 1 or index.get("retention") != EXPECTED_RETENTION:
        errors.append("external artifact index policy mismatch")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("external artifact index requires artifacts")
        return None
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("staging_path") == package_path
    ]
    if len(matches) != 1:
        errors.append(f"detached package requires exactly one external artifact record: {package_path}")
        return None
    artifact = matches[0]
    for name in ("sha256", "size", "members"):
        if artifact.get(name) != reference.get(name):
            errors.append(f"detached package {name} mismatch: {package_path}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256", ""))):
        errors.append(f"detached package SHA-256 is invalid: {package_path}")
    if not isinstance(artifact.get("size"), int) or artifact["size"] <= 5 * 1024 * 1024:
        errors.append(f"detached package size is invalid: {package_path}")
    if not isinstance(artifact.get("members"), list) or not artifact["members"]:
        errors.append(f"detached package member table is missing: {package_path}")
    if artifact.get("archive_status") not in {"PENDING_UPLOAD", "ARCHIVED"}:
        errors.append(f"detached package archive status is invalid: {package_path}")
    if not isinstance(artifact.get("key_excerpt"), dict) or not artifact["key_excerpt"]:
        errors.append(f"detached package key excerpt is missing: {package_path}")
    return artifact
