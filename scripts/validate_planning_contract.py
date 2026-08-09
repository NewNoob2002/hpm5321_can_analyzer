#!/usr/bin/env python3
"""Validate the normalized SPI2 SD/LED planning contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("docs/approved-plan/planning-contract.json")


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {relative}: {exc}")
        return ""


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def _profile_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if match and match.group(1) not in {"Key", "---"}:
            rows[match.group(1).strip()] = match.group(2).strip()
    return rows


def _load_contract(root: Path, errors: list[str]) -> dict[str, Any]:
    raw = _read(root, str(CONTRACT_PATH), errors)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid planning contract JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("planning contract root must be an object")
        return {}
    return value


def validate(root: Path, require_storage_frozen: bool = False) -> list[str]:
    errors: list[str] = []
    contract = _load_contract(root, errors)
    if not contract:
        return errors

    addendum_id = contract.get("addendum_id")
    if addendum_id != "spi2-sd-led-2026-08-09":
        errors.append("stable addendum ID mismatch")
    if contract.get("status") != "APPROVED":
        errors.append("planning contract is not APPROVED")

    texts: dict[str, str] = {}

    def text_for(relative: str) -> str:
        if relative not in texts:
            texts[relative] = _read(root, relative, errors)
        return texts[relative]

    for relative in contract.get("id_documents", []):
        if addendum_id not in text_for(relative):
            errors.append(f"stable addendum ID missing from {relative}")

    for pin in contract.get("pins", []):
        token = f"| {pin['signal']} | {pin['pin']} |"
        for relative in contract.get("pin_documents", []):
            if token not in text_for(relative):
                errors.append(
                    f"pin map mismatch for {pin['signal']}={pin['pin']} in {relative}"
                )

    for relative, tokens in contract.get("source_tokens", {}).items():
        source = text_for(relative)
        for token in tokens:
            if token not in source:
                errors.append(f"source token missing from {relative}: {token}")

    for product_name, peripheral in contract.get("channel_aliases", {}).items():
        token = f"{product_name} = {peripheral}"
        for relative in contract.get("alias_documents", []):
            if token not in text_for(relative):
                errors.append(f"channel alias {token} missing from {relative}")

    test_spec = text_for("docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md")
    prd = text_for("docs/approved-plan/prd-hpm5321-usb-can-analyzer.md")
    for test in contract.get("led_tests", []):
        registry = f"| {test['id']} | {test['gate']} | {test['applicability']} |"
        definition = f"- `{test['id']}`"
        if registry not in test_spec:
            errors.append(f"LED test registry mismatch: {test['id']}")
        if test_spec.count(definition) != 1:
            errors.append(f"LED test definition must be unique: {test['id']}")
        if test["id"] not in prd:
            errors.append(f"LED test traceability missing from PRD: {test['id']}")

    release = contract.get("release_contract", {})
    chain = release.get("conditional_chain", "")
    claim_scope = release.get("claim_scope", "")
    for relative in release.get("documents", []):
        content = text_for(relative)
        if chain not in content:
            errors.append(f"release chain mismatch in {relative}")
        if claim_scope not in content:
            errors.append(f"release applicability mismatch in {relative}")

    profile_spec = contract.get("profile", {})
    profile_path = profile_spec.get("path", "")
    profile_text = text_for(profile_path)
    rows = _profile_rows(profile_text)
    if "TBD" in profile_text.upper():
        errors.append("storage profile contains TBD")
    for field in profile_spec.get("required_fields", []):
        if not rows.get(field):
            errors.append(f"storage profile field missing: {field}")
    status = rows.get("status")
    if status not in profile_spec.get("allowed_statuses", []):
        errors.append(f"invalid storage profile status: {status}")
    if require_storage_frozen:
        if status != "FROZEN":
            errors.append("storage profile is not FROZEN")
        for field in profile_spec.get("freeze_numeric_fields", []):
            value = rows.get(field, "")
            try:
                if float(value) <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"frozen storage profile field is not positive numeric: {field}")

    for approval in contract.get("approvals", []):
        content = text_for(approval["file"])
        if content.count(approval["heading"]) != 1:
            errors.append(f"approval heading count mismatch: {approval['role']}")
            continue
        section = _section(content, approval["heading"])
        required = (
            addendum_id,
            f"Verdict: `{approval['verdict']}`",
            f"Sequence: {approval['sequence']}",
        )
        if any(token not in section for token in required):
            errors.append(f"approval section mismatch: {approval['role']}")

    handoff_spec = contract.get("handoff", {})
    handoff_text = text_for(handoff_spec.get("file", ""))
    handoff_section = _section(handoff_text, handoff_spec.get("heading", ""))
    handoff_tokens = (
        addendum_id,
        "complete: true",
        "execution_authorized: true",
        f"approved_order: {handoff_spec.get('approved_order')}",
        "Architect sequence: 1",
        "Critic sequence: 2",
    )
    if not handoff_section or any(token not in handoff_section for token in handoff_tokens):
        errors.append("handoff entry is missing, incomplete or out of order")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--require-storage-frozen", action="store_true")
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.require_storage_frozen)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    mode = "frozen" if args.require_storage_frozen else "structural"
    print(f"PASS planning contract ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
