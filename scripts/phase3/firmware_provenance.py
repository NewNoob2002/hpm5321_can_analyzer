"""Fail-closed firmware build-manifest validation for Phase 3 HIL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ARTIFACTS = ("demo.elf", "demo.bin")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _required_string(manifest: dict[str, Any], name: str) -> str:
    value = manifest.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"firmware manifest field {name} is missing or empty")
    return value


def _required_hex(manifest: dict[str, Any], name: str, pattern: re.Pattern[str]) -> str:
    value = _required_string(manifest, name).lower()
    if not pattern.fullmatch(value):
        raise RuntimeError(f"firmware manifest field {name} has an invalid hash")
    return value


def verified_firmware_manifest(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    root = root.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read firmware manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise RuntimeError("firmware manifest schema must be 1")

    preset = _required_string(manifest, "preset")
    source_revision = _required_hex(manifest, "source_revision", HEX_40)
    source_dirty = manifest.get("source_dirty")
    if not isinstance(source_dirty, bool):
        raise RuntimeError("firmware manifest field source_dirty must be boolean")
    sdk_commit = _required_hex(manifest, "sdk_commit", HEX_40)
    compiler = _required_string(manifest, "compiler")
    build_options = manifest.get("build_options")
    if not isinstance(build_options, dict) or not isinstance(
        build_options.get("APP_USB_FORCE_FULL_SPEED"), bool
    ):
        raise RuntimeError(
            "firmware manifest build option APP_USB_FORCE_FULL_SPEED is missing"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("firmware manifest artifacts are missing")
    verified_artifacts: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_ARTIFACTS:
        entry = artifacts.get(name)
        if not isinstance(entry, dict):
            raise RuntimeError(f"firmware manifest artifact {name} is missing")
        expected_sha256 = entry.get("sha256")
        expected_size = entry.get("size")
        if not isinstance(expected_sha256, str) or not HEX_64.fullmatch(
            expected_sha256.lower()
        ):
            raise RuntimeError(f"firmware manifest artifact {name} has an invalid hash")
        if not isinstance(expected_size, int) or expected_size <= 0:
            raise RuntimeError(f"firmware manifest artifact {name} has an invalid size")

        artifact_path = manifest_path.parent / "output" / name
        if not artifact_path.is_file():
            raise RuntimeError(f"firmware artifact is missing: {artifact_path}")
        measured_size = artifact_path.stat().st_size
        measured_sha256 = _sha256(artifact_path)
        if measured_size != expected_size or measured_sha256 != expected_sha256.lower():
            raise RuntimeError(f"firmware artifact does not match manifest: {artifact_path}")
        verified_artifacts[name] = {
            "path": _display_path(artifact_path, root),
            "size": measured_size,
            "sha256": measured_sha256,
            "verified": True,
        }

    return {
        "path": _display_path(manifest_path, root),
        "sha256": _sha256(manifest_path),
        "preset": preset,
        "source_revision": source_revision,
        "source_dirty": source_dirty,
        "sdk_commit": sdk_commit,
        "compiler": compiler,
        "build_options": build_options,
        "elf_sha256": verified_artifacts["demo.elf"]["sha256"],
        "bin_sha256": verified_artifacts["demo.bin"]["sha256"],
        "verified_artifacts": verified_artifacts,
        "association_method": "operator-selected manifest with verified host build artifacts",
        "device_attested": False,
        "boundary": "the raw echo firmware does not expose an on-device build identifier",
    }
