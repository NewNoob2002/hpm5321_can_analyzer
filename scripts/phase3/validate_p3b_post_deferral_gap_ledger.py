#!/usr/bin/env python3
"""Fail-closed validation for the post-P3B-deferral gap ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = Path("docs/development/p3b-post-deferral-gap-ledger.json")
DEFAULT_OWNERSHIP = Path("docs/development/p3b-post-deferral-file-ownership.json")
BASE_SHA = "03670f16e1c8178525ac9c43a59c1e2f555f6945"

REQUIRED_IDS = {
    *(f"T-PROTO-{value:03d}" for value in range(1, 13)),
    "T-E2E-001", "T-E2E-002", "T-E2E-003", "T-E2E-004",
    "T-E2E-005", "T-E2E-006", "T-E2E-007", "T-E2E-008",
    "T-E2E-009",
    "T-FW-001", "T-FW-002", "T-FW-003", "T-FW-004",
    "T-FW-005", "T-FW-006", "T-FW-007", "T-FW-008",
    "T-FW-009", "T-FW-010", "T-FW-011", "T-FW-012",
    "T-FW-013",
    "T-HOST-001", "T-HOST-002", "T-HOST-003", "T-HOST-004",
    "T-HOST-005",
    "T-CAN-002", "T-CAN-005", "T-CAN-009",
    "T-LED-004", "T-LED-005",
}

EXPECTED_INVARIANTS = {
    "P3B": "PARTIAL",
    "P4E": "BLOCKED",
    "freeze_ready": False,
    "hardware_bus_off": "NOT_COMPLETED",
    "hardware_execution_authorized": False,
    "bus_off_gate": "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
    "development_continuation": "AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE",
    "single_channel_before_dual_channel": True,
    "MVP": "OPEN",
    "Beta": "OPEN",
    "release": "OPEN",
}
EXPECTED_AUTHORITY = {
    "path": "docs/evidence/phase3/P3B-bus-off-fault-injection-blocker-2026-08-15.json",
    "sha256": "7abce66e01869eca723058b502a70110ac859b62b42ea1cb908d648157c82ca4",
    "authority": "HISTORICAL_ONLY",
    "preserve_original": True,
}
REQUIRED_ENTRY_FIELDS = {
    "test_id", "gate", "work_package", "requirement_ids", "scope",
    "implementation_status", "software_verification_status",
    "hardware_evidence_status", "qualification_status",
    "conservative_status", "owner_role", "implementation_paths",
    "evidence_paths", "evidence_source_identity", "artifact_identity",
    "dependencies", "blockers", "next_action", "notes",
}
CONSERVATIVE = {"PASS", "PARTIAL", "BLOCKED", "NOT_TESTED"}
IMPLEMENTATION = {"IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED", "DEFERRED"}
VERIFICATION = {"PASS", "PARTIAL", "NOT_TESTED", "BLOCKED", "DEFERRED"}
HARDWARE = {"PARTIAL", "NOT_TESTED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE"}
QUALIFICATION = {"OPEN", "BLOCKED", "DEFERRED"}
ARTIFACT_STATUSES = {"BOUND", "NOT_PRODUCED", "NOT_EXECUTED"}
ARTIFACT_KINDS = {
    "REPOSITORY_GIT_BLOB",
    "EXTERNAL_SHA256",
    "QUALIFICATION_CLOSURE_ARTIFACT",
}
ARTIFACT_ROLES = {"EVIDENCE_ARTIFACT", "STATUS_RECORD"}

EXPECTED_WAVE_WRITERS = {
    0: {
        "A1_WP0_GOVERNANCE_COORDINATOR": [
            "docs/development/p3b-post-deferral-gap-ledger.json",
            "docs/development/p3b-post-deferral-file-ownership.json",
            "scripts/phase3/validate_p3b_post_deferral_gap_ledger.py",
            "tests/phase3/test_p3b_post_deferral_gap_ledger.py",
        ],
    },
    1: {
        "B1_PROTOCOL_HOST_CORE_OWNER": [
            "protocol/v1/**",
            "host/crates/protocol/**",
            "host/crates/core/src/transport.rs",
            "host/crates/core/src/fake.rs",
            "host/crates/core/src/lib.rs",
            "tests/protocol/**",
            "host/crates/core/tests/**",
        ],
    },
    2: {
        "C1_SINGLE_CHANNEL_FIRMWARE_INTEGRATOR": [
            "USER/src/app_mcan0_owner.c",
            "USER/inc/app_mcan0_owner.h",
            "USER/src/app_usb_owner.c",
            "USER/inc/app_usb_owner.h",
            "tests/phase3/test_mcan0_owner_contract.py",
            "tests/phase3/test_usb_owner_contract.py",
        ],
        "C2_HOST_CLI_VERTICAL_SLICE": [
            "host/crates/cli/**",
            "host/crates/application/**",
        ],
    },
    3: {
        "D1_FIRMWARE_RELIABILITY_OWNER": [
            "WP2_POST_MERGE_REISSUE_REQUIRED",
        ],
        "D2_LINUX_WINDOWS_PRODUCTIZATION_OWNER": [
            "host/crates/cli/**",
            "packaging/linux/**",
            "packaging/windows/**",
        ],
    },
    4: {
        "E1_DUAL_CHANNEL_OWNER": [
            "CHANNEL_NEUTRAL_SCOPE_REQUIRES_EXACT_REISSUE",
            "MCAN2_SCOPE_REQUIRES_EXACT_REISSUE",
            "NON_HARDWARE_EVIDENCE_SCOPE_REQUIRES_EXACT_REISSUE",
        ],
    },
}


def repository_file(root: Path, value: object, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"invalid {label}")
        return None
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        errors.append(f"invalid {label}: {value}")
        return None
    path = root / value
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError):
        errors.append(f"missing {label}: {value}")
        return None
    if path.is_symlink() or not resolved.is_file():
        errors.append(f"{label} must be a regular repository file: {value}")
        return None
    return resolved


def safe_pattern(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if value.startswith("/"):
        return False
    return not any(part in {"", ".", ".."} for part in value.split("/"))


def git_blob(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def baseline_git_blob(
    root: Path, path: str, label: str, errors: list[str]
) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{BASE_SHA}:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"{label} baseline Git lookup failed: {exc}")
        return None
    if result.returncode != 0:
        errors.append(f"{label} is not present at baseline commit")
        return None
    object_id = result.stdout.strip()
    if len(object_id) != 40 or any(c not in "0123456789abcdef" for c in object_id):
        errors.append(f"{label} baseline Git lookup returned an invalid object")
        return None
    try:
        object_type = subprocess.run(
            ["git", "cat-file", "-t", object_id],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"{label} baseline Git type lookup failed: {exc}")
        return None
    if object_type.returncode != 0 or object_type.stdout.strip() != "blob":
        errors.append(f"{label} baseline object is not a blob")
        return None
    return object_id


def validate_git_blob_binding(
    root: Path,
    path: object,
    blob: object,
    label: str,
    errors: list[str],
) -> None:
    evidence_file = repository_file(root, path, label, errors)
    if evidence_file is None:
        return
    if not isinstance(blob, str) or len(blob) != 40 or any(
        c not in "0123456789abcdef" for c in blob
    ):
        errors.append(f"{label} has invalid blob")
        return
    baseline_blob = baseline_git_blob(root, path, label, errors)
    if baseline_blob is not None and baseline_blob != blob:
        errors.append(f"{label} baseline blob mismatch")
    if git_blob(evidence_file) != blob:
        errors.append(f"{label} working tree blob mismatch")


def load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return None
    return value


def validate_source_identity(root: Path, evidence_paths: object, identities: object, label: str, errors: list[str]) -> None:
    if not isinstance(evidence_paths, list) or not evidence_paths:
        errors.append(f"{label} requires evidence_paths")
        return
    if not isinstance(identities, list) or len(identities) != len(evidence_paths):
        errors.append(f"{label} evidence/source identity cardinality mismatch")
        return
    for index, (evidence, identity) in enumerate(zip(evidence_paths, identities)):
        if not isinstance(identity, dict):
            errors.append(f"{label} source identity[{index}] must be an object")
            continue
        if identity.get("type") != "git_blob" or identity.get("commit") != BASE_SHA:
            errors.append(f"{label} source identity[{index}] is not baseline-bound")
        if identity.get("path") != evidence:
            errors.append(f"{label} source identity[{index}] path mismatch")
        validate_git_blob_binding(
            root,
            evidence,
            identity.get("blob"),
            f"{label} source identity[{index}]",
            errors,
        )


def validate_artifact_identity(
    root: Path,
    artifacts: object,
    evidence_paths: object,
    source_identities: object,
    owner_role: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(artifacts, list) or not artifacts:
        errors.append(f"{label} artifact_identity must be a non-empty array")
        return

    evidence = evidence_paths if isinstance(evidence_paths, list) else []
    source_values = source_identities if isinstance(source_identities, list) else []
    source_by_path = {
        identity.get("path"): identity
        for identity in source_values
        if isinstance(identity, dict)
        and isinstance(identity.get("path"), str)
    }
    bound_paths: set[str] = set()
    has_explicit_closure_state = False
    for index, artifact in enumerate(artifacts):
        artifact_label = f"{label} artifact_identity[{index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{artifact_label} must be an object")
            continue
        status = artifact.get("status")
        kind = artifact.get("kind")
        if status not in ARTIFACT_STATUSES:
            errors.append(f"{artifact_label} has invalid status")
            continue
        if kind not in ARTIFACT_KINDS:
            errors.append(f"{artifact_label} has invalid kind")
            continue

        if status == "BOUND":
            if kind == "REPOSITORY_GIT_BLOB":
                path = artifact.get("path")
                role = artifact.get("role")
                if role not in ARTIFACT_ROLES:
                    errors.append(f"{artifact_label} has invalid or empty role")
                if artifact.get("commit") != BASE_SHA:
                    errors.append(f"{artifact_label} is not baseline-bound")
                if path not in evidence:
                    errors.append(f"{artifact_label} path is not an evidence path")
                if isinstance(path, str) and path in bound_paths:
                    errors.append(f"{artifact_label} duplicates a bound artifact path")
                if isinstance(path, str):
                    bound_paths.add(path)
                    expected_role = (
                        "EVIDENCE_ARTIFACT"
                        if path.startswith("docs/evidence/")
                        else "STATUS_RECORD"
                    )
                    if role != expected_role:
                        errors.append(f"{artifact_label} role/path mismatch")
                source = source_by_path.get(path)
                if not isinstance(source, dict) or any(
                    artifact.get(field) != source.get(field)
                    for field in ("path", "commit", "blob")
                ):
                    errors.append(f"{artifact_label} source identity mismatch")
                validate_git_blob_binding(
                    root,
                    path,
                    artifact.get("blob"),
                    artifact_label,
                    errors,
                )
            elif kind == "EXTERNAL_SHA256":
                identifier = artifact.get("identifier")
                digest = artifact.get("sha256")
                source_record = artifact.get("source_record_path")
                if not isinstance(identifier, str) or not identifier.strip():
                    errors.append(f"{artifact_label} has invalid external identifier")
                if not isinstance(digest, str) or len(digest) != 64 or any(
                    character not in "0123456789abcdef" for character in digest
                ):
                    errors.append(f"{artifact_label} has invalid external sha256")
                if source_record not in evidence:
                    errors.append(f"{artifact_label} external source record mismatch")
            else:
                errors.append(f"{artifact_label} BOUND status requires an identity kind")
        else:
            has_explicit_closure_state = True
            if kind != "QUALIFICATION_CLOSURE_ARTIFACT":
                errors.append(f"{artifact_label} unresolved status has invalid kind")
            reason = artifact.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{artifact_label} missing reason")
            expected_owner = artifact.get("expected_owner")
            if (
                not isinstance(expected_owner, str)
                or not expected_owner.strip()
                or expected_owner != owner_role
            ):
                errors.append(f"{artifact_label} expected_owner mismatch")
            if any(field in artifact for field in ("path", "blob", "sha256")):
                errors.append(f"{artifact_label} unresolved artifact cannot claim identity")

    if not has_explicit_closure_state:
        errors.append(f"{label} artifact_identity lacks explicit closure state")


def validate_ledger(root: Path, ledger: dict[str, Any], errors: list[str]) -> None:
    if ledger.get("schema_version") != 1:
        errors.append("ledger schema_version mismatch")
    if ledger.get("generated_from_commit") != BASE_SHA:
        errors.append("ledger generated_from_commit mismatch")
    planning_contract = ledger.get("planning_contract")
    if not isinstance(planning_contract, dict):
        errors.append("ledger planning_contract must be an object")
    else:
        if planning_contract.get("path") != "docs/development/p3b-next-step-work-plan.md":
            errors.append("planning contract path mismatch")
        validate_git_blob_binding(
            root,
            planning_contract.get("path"),
            planning_contract.get("blob"),
            "planning contract",
            errors,
        )
    invariants = ledger.get("governance_invariants")
    if not isinstance(invariants, dict):
        errors.append("ledger governance_invariants must be an object")
    else:
        for key, expected in EXPECTED_INVARIANTS.items():
            if invariants.get(key) != expected:
                errors.append(f"governance invariant mismatch: {key}")
    authoritative = ledger.get("authoritative_status")
    if not isinstance(authoritative, dict):
        errors.append("ledger authoritative_status must be an object")
    else:
        if authoritative.get("path") != "docs/evidence/phase3/P3B-current-status.json":
            errors.append("authoritative status path mismatch")
        validate_git_blob_binding(
            root,
            authoritative.get("path"),
            authoritative.get("blob"),
            "authoritative status",
            errors,
        )
        expected = {
            "qualification_status": "PARTIAL", "p4e_gate": "BLOCKED",
            "freeze_ready": False, "hardware_bus_off": "NOT_COMPLETED",
            "hardware_execution_authorized": False,
            "bus_off_gate": "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY",
        }
        for key, value in expected.items():
            if authoritative.get(key) != value:
                errors.append(f"authoritative status mismatch: {key}")
        if authoritative.get("historical_blocker") != EXPECTED_AUTHORITY:
            errors.append("historical blocker authority was redefined")

    entries = ledger.get("entries")
    if not isinstance(entries, list):
        errors.append("ledger entries must be an array")
        return
    seen: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(entries):
        label = f"entry[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(REQUIRED_ENTRY_FIELDS - item.keys())
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}")
        test_id = item.get("test_id")
        if not isinstance(test_id, str) or not test_id:
            errors.append(f"{label} missing test_id")
            continue
        if test_id in seen:
            errors.append(f"duplicate test ID: {test_id}")
        seen.add(test_id)
        by_id[test_id] = item
        if not isinstance(item.get("owner_role"), str) or not item.get("owner_role", "").strip():
            errors.append(f"{test_id} missing owner_role")
        if not isinstance(item.get("next_action"), str) or not item.get("next_action", "").strip():
            errors.append(f"{test_id} missing next_action")
        for field in ("requirement_ids", "blockers"):
            values = item.get(field)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
            ):
                errors.append(f"{test_id} invalid or empty {field}")
        validate_artifact_identity(
            root,
            item.get("artifact_identity"),
            item.get("evidence_paths"),
            item.get("evidence_source_identity"),
            item.get("owner_role"),
            test_id,
            errors,
        )
        if item.get("implementation_status") not in IMPLEMENTATION:
            errors.append(f"{test_id} invalid implementation_status")
        if item.get("software_verification_status") not in VERIFICATION:
            errors.append(f"{test_id} invalid software_verification_status")
        if item.get("hardware_evidence_status") not in HARDWARE:
            errors.append(f"{test_id} hardware evidence status upgrade or invalid value")
        if item.get("qualification_status") not in QUALIFICATION:
            errors.append(f"{test_id} qualification status upgrade or invalid value")
        if item.get("conservative_status") not in CONSERVATIVE:
            errors.append(f"{test_id} invalid conservative_status")
        for field in ("implementation_paths", "dependencies"):
            values = item.get(field)
            if not isinstance(values, list) or any(not safe_pattern(value) for value in values):
                errors.append(f"{test_id} invalid {field}")
        validate_source_identity(root, item.get("evidence_paths"), item.get("evidence_source_identity"), test_id, errors)
        if item.get("conservative_status") == "PASS":
            if not item.get("evidence_paths") or not item.get("evidence_source_identity"):
                errors.append(f"{test_id} PASS requires evidence and source identity")
            if item.get("qualification_status") != "OPEN":
                errors.append(f"{test_id} PASS cannot imply qualification closure")

    missing_ids = sorted(REQUIRED_IDS - seen)
    extra_ids = sorted(seen - REQUIRED_IDS)
    if missing_ids:
        errors.append("missing required test IDs: " + ", ".join(missing_ids))
    if extra_ids:
        errors.append("unapproved test IDs: " + ", ".join(extra_ids))

    e2e009 = by_id.get("T-E2E-009", {})
    if e2e009.get("conservative_status") == "PASS" or e2e009.get("hardware_evidence_status") not in {"BLOCKED", "DEFERRED"}:
        errors.append("T-E2E-009 cannot be closed by software or split evidence")
    fw003 = by_id.get("T-FW-003", {})
    if fw003.get("owner_role") != "M1_BUS_OFF_CAPABILITY_MONITOR" or fw003.get("implementation_status") != "DEFERRED" or fw003.get("conservative_status") != "BLOCKED":
        errors.append("T-FW-003 must remain in the deferred lane")
    host003 = by_id.get("T-HOST-003", {})
    if host003.get("implementation_status") != "DEFERRED" or host003.get("conservative_status") == "PASS":
        errors.append("T-HOST-003 macOS must remain deferred")


def validate_ownership(ownership: dict[str, Any], errors: list[str]) -> None:
    if ownership.get("schema_version") != 1:
        errors.append("ownership schema_version mismatch")
    if ownership.get("generated_from_commit") != BASE_SHA:
        errors.append("ownership generated_from_commit mismatch")
    if ownership.get("work_order") != ["WP0", "WP1", "WP2", "WP3||WP4", "WP5"]:
        errors.append("work-package order must preserve single-channel before dual-channel")
    waves = ownership.get("waves")
    if not isinstance(waves, list) or [wave.get("wave") for wave in waves if isinstance(wave, dict)] != [0, 1, 2, 3, 4]:
        errors.append("ownership waves must be ordered 0 through 4")
        return
    for wave in waves:
        wave_id = wave.get("wave")
        writers = wave.get("writers", {})
        if not isinstance(writers, dict):
            errors.append(f"wave {wave_id} writers must be an object")
            continue
        if writers != EXPECTED_WAVE_WRITERS.get(wave_id):
            errors.append(f"wave {wave_id} writers do not match authorized manifest")
        read_only_roles = wave.get("read_only_roles", [])
        if not isinstance(read_only_roles, list) or any(
            not isinstance(role, str) or not role for role in read_only_roles
        ):
            errors.append(f"wave {wave_id} read_only_roles must be an array")
            read_only_roles = []
        for role in sorted(set(read_only_roles).intersection(writers)):
            errors.append(f"wave {wave_id} read-only role cannot be a writer: {role}")
        claims: dict[str, str] = {}
        for role, patterns in writers.items():
            if not isinstance(patterns, list):
                errors.append(f"writer {role} patterns must be an array")
                continue
            for pattern in patterns:
                if not safe_pattern(pattern):
                    errors.append(f"writer {role} has invalid pattern")
                    continue
                previous = claims.get(pattern)
                if previous is not None and previous != role:
                    errors.append(f"multiple writers in wave {wave_id} for {pattern}")
                claims[pattern] = role
    if waves[1].get("start_gate") != "A2_APPROVE_WP0" or waves[1].get("completion_gate") != "B2_INTERFACE_FREEZE_ACCEPTED":
        errors.append("WP1 must wait for A2 and end at B2 interface freeze")
    if waves[2].get("start_gate") != "B2_INTERFACE_FREEZE_ACCEPTED":
        errors.append("WP2 must wait for the protocol interface freeze")
    if waves[3].get("start_gate") != "C3_APPROVE_WP2_SOFTWARE_INTEGRATION" or waves[3].get("parallel") is not True:
        errors.append("WP3/WP4 may run in parallel only after WP2 acceptance")
    if waves[4].get("start_gate") != "WP2_ACCEPTED_AND_RELEVANT_WP3_SAFETY_CONTROLS_ACCEPTED":
        errors.append("WP5 must depend on WP2 and relevant WP3 safety controls")

    hotspots = ownership.get("exclusive_hotspots")
    if not isinstance(hotspots, list):
        errors.append("exclusive_hotspots must be an array")
        hotspots = []
    hotspot_by_id = {item.get("hotspot_id"): item for item in hotspots if isinstance(item, dict)}
    b1 = hotspot_by_id.get("B1_PROTOCOL_AND_HOST_CORE", {})
    c1 = hotspot_by_id.get("C1_SINGLE_CHANNEL_FIRMWARE", {})
    c2 = hotspot_by_id.get("C2_APPLICATION_LAYER_ONLY", {})
    if b1.get("owner_role") != "B1_PROTOCOL_HOST_CORE_OWNER" or b1.get("other_writers_forbidden") is not True:
        errors.append("B1 protocol/Host Core hotspot must have one exclusive writer")
    if c1.get("owner_role") != "C1_SINGLE_CHANNEL_FIRMWARE_INTEGRATOR" or c1.get("other_writers_forbidden") is not True:
        errors.append("C1 firmware-owner hotspot must have one exclusive writer")
    required_c1 = {"USER/src/app_mcan0_owner.c", "USER/inc/app_mcan0_owner.h", "USER/src/app_usb_owner.c", "USER/inc/app_usb_owner.h"}
    if not required_c1.issubset(set(c1.get("patterns", []))):
        errors.append("C1 hotspot list is incomplete")
    c2_patterns = set(c2.get("patterns", []))
    if any(pattern.startswith(("protocol/v1/", "host/crates/protocol/", "host/crates/core/", "USER/")) for pattern in c2_patterns):
        errors.append("C2 cannot own protocol, Host Core, or firmware hotspots")
    d1_patterns = waves[3].get("writers", {}).get("D1_FIRMWARE_RELIABILITY_OWNER", [])
    if required_c1.intersection(d1_patterns) and "REAUTHORIZED_C1_HOTSPOTS_AFTER_WP2" not in d1_patterns:
        errors.append("D1 cannot own C1 hotspots without reauthorization")

    deferred = ownership.get("deferred_lane")
    if not isinstance(deferred, dict):
        errors.append("deferred_lane must be an object")
    else:
        if deferred.get("owner_role") != "M1_BUS_OFF_CAPABILITY_MONITOR" or deferred.get("read_only") is not True:
            errors.append("M1 must remain read-only")
        if deferred.get("hardware_execution_authorized") is not False or deferred.get("hardware_commands") != []:
            errors.append("M1 cannot receive hardware execution authority or commands")
        if deferred.get("status") != "DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY":
            errors.append("active bus-off must remain deferred")
    if ownership.get("preserved_authorities") != [EXPECTED_AUTHORITY]:
        errors.append("historical blocker authority was redefined in ownership manifest")
    excluded = ownership.get("excluded_dependency_graph")
    if excluded != ["macOS", "Qt", "GUI", "STORAGE", "UPDATE"]:
        errors.append("macOS/Qt/GUI/STORAGE/UPDATE must remain outside the dependency graph")


def validate(root: Path = ROOT, ledger_path: Path = DEFAULT_LEDGER, ownership_path: Path = DEFAULT_OWNERSHIP) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    ledger_file = repository_file(root, ledger_path.as_posix(), "gap ledger", errors)
    ownership_file = repository_file(root, ownership_path.as_posix(), "ownership manifest", errors)
    if ledger_file is None or ownership_file is None:
        return errors
    ledger = load_json(ledger_file, "gap ledger", errors)
    ownership = load_json(ownership_file, "ownership manifest", errors)
    if ledger is not None:
        validate_ledger(root, ledger, errors)
    if ownership is not None:
        validate_ownership(ownership, errors)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--ownership", type=Path, default=DEFAULT_OWNERSHIP)
    args = parser.parse_args()
    errors = validate(args.root, args.ledger, args.ownership)
    if errors:
        raise SystemExit("\n".join(f"ERROR: {error}" for error in errors))
    print(f"PASS P3B post-deferral gap ledger entries={len(REQUIRED_IDS)} invariants=preserved")


if __name__ == "__main__":
    main()
