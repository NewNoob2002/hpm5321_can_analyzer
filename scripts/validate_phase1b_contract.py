#!/usr/bin/env python3
"""Validate Phase 1B closure evidence and gate ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("docs/evidence/phase1/phase1b-closure.json")


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {relative}: {exc}")
        return ""
    if not text.strip():
        errors.append(f"empty evidence file: {relative}")
    return text


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    raw = _read(root, str(MANIFEST), errors)
    if not raw:
        return errors
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [*errors, f"invalid Phase 1B manifest JSON: {exc}"]

    if manifest.get("phase") != "1B" or manifest.get("status") != "PASS":
        errors.append("Phase 1B manifest is not PASS")

    required = manifest.get("required_gates", {})
    if not required:
        errors.append("Phase 1B required gate set is empty")
    for name, gate in required.items():
        if gate.get("status") != "PASS":
            errors.append(f"required Phase 1B gate is not PASS: {name}")
        evidence = gate.get("evidence", [])
        if not evidence:
            errors.append(f"required Phase 1B gate has no evidence: {name}")
        for relative in evidence:
            _read(root, relative, errors)

    deferred = manifest.get("deferred_non_gating", {})
    for key in (
        "physical_cable_hotplug",
        "windows_pnp_binding_and_release_artifact_provenance",
        "openocd",
        "macos",
    ):
        if key not in deferred:
            errors.append(f"deferred Phase 1B boundary missing: {key}")

    checks = {
        "docs/development/phase1-status.md": (
            "| Phase 1B closure | PASS |",
            "J-Link is selected",
        ),
        "docs/approved-plan/scope-addendum-linux-windows-cli.md": (
            "Phase 1B closure: `PASS`",
            "Physical cable cycling is PASS at P3A/T-USB-007",
        ),
        "docs/development/adr-host-stack-spike.md": (
            "Status: **ACCEPTED**",
            "Real Linux and Windows vendor-Bulk functional lanes: **PASS**",
        ),
        "docs/approved-plan/prd-hpm5321-usb-can-analyzer.md": (
            "J-Link GDB Server 是选中的 MVP adapter",
            "Linux/Windows 各完成 clean configure/build；macOS 按当前 CLI scope deferred",
        ),
        "docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md": (
            "| T-USB-004 | P2 | deferred(current Linux/Windows CLI scope) |",
            "| T-HOST-003 | P2 | deferred(current Linux/Windows CLI scope) |",
        ),
        "docs/evidence/phase1/T-HOST-USB-WINDOWS-report.md": (
            "Phase 1B lane: `PASS`",
            "Product PnP/package evidence: `PARTIAL`",
        ),
        "docs/evidence/phase1/T-HOST-WINDOWS-CI-report.md": (
            "30886654542",
            "rustc `1.97.1",
            "All four steps passed",
        ),
        "docs/evidence/phase1/T-DEV-005-jlink-gdb-report.md": (
            "Breakpoint 1, main",
            "stepi",
            "monitor reset",
        ),
        ".github/workflows/host-rust.yml": (
            "os: [ubuntu-latest, windows-latest]",
            "toolchain install 1.97.1",
        ),
        ".vscode/launch.json": (
            '"miDebuggerServerAddress": "localhost:2331"',
            '"break main"',
        ),
    }
    for relative, tokens in checks.items():
        text = _read(root, relative, errors)
        for token in tokens:
            if token not in text:
                errors.append(f"Phase 1B closure token missing from {relative}: {token}")

    stale_tokens = {
        "docs/approved-plan/scope-addendum-linux-windows-cli.md": (
            "Formal protocol codec implementation begins only after",
        ),
        "docs/development/adr-host-stack-spike.md": (
            "Formal host codec work remains prohibited",
            "USB integration pending",
        ),
        "docs/implementation-status.md": (
            "Clean official-SDK builds remain required",
        ),
        "docs/approved-plan/prd-hpm5321-usb-can-analyzer.md": (
            "Linux/Windows/macOS 至少各完成一次 clean configure/build",
            "在任何 host codec/CLI 实现前",
        ),
    }
    for relative, tokens in stale_tokens.items():
        text = _read(root, relative, errors)
        for token in tokens:
            if token in text:
                errors.append(f"stale Phase 1B blocker remains in {relative}: {token}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS Phase 1B closure contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
