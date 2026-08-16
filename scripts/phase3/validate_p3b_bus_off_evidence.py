#!/usr/bin/env python3
"""Validate P3B bus-off manual-HIL readiness without accepting a fake HIL PASS."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(
    "docs/evidence/phase3/P3B-bus-off-fault-injection-readiness-2026-08-15.json"
)
EXPECTED_SOURCE_HASHES = {
    "CMakeLists.txt": (
        "d86c742d87e1c1dca467639f3c7e30a671aabd62edc4cab5b43f6810b35e743a"
    ),
    "CMakePresets.json": (
        "8fab38287bcd6ddd5b0aa050cf7dc40dd9bdf31389e8f7daf04e56ab16d4d216"
    ),
    "USER/inc/app_mcan0_owner.h": (
        "d2de1d1d44b34347639cee2f35f5466c9446f4621768613fd23e2af743774755"
    ),
    "USER/src/app_mcan0_owner.c": (
        "68ce29e26cdf4d74ce883e898f28d92a8a694cd84cc1ecb416db27775c4b6063"
    ),
    "boards/hpm5321_custom/board.c": (
        "fabcf86f370780591c13139b390225884edf7209512ed1e26e97acedbf0e60a1"
    ),
    "boards/hpm5321_custom/board.h": (
        "2d50dbb54652080f5e8b3a92159f86773193dbc00307f7f5ad82689c79038d0a"
    ),
    "boards/hpm5321_custom/pinmux.c": (
        "fc0ba3913efe53f55cdcc0edd103cc0fc0b3a2ffb10a266305b3d16ab05d1868"
    ),
    "boards/hpm5321_custom/pinmux.h": (
        "f3a1cd29792ff60a2102f08fed566749e6f8a336b184979ca5dfdcb676d82f38"
    ),
    "scripts/build.sh": (
        "655bde0805776043ec619ac0f74c4113bb2e0026c5dcc6ff8c5d52c906f91640"
    ),
    "scripts/env/check_memory_budget.py": (
        "d499f1b66556e1073c1214bfdb39ef3f2bd19089fb8a0428703cb73b7e58e6bf"
    ),
    "scripts/env/write_build_manifest.py": (
        "fbe6fa303d9f1adb57f583541273df3c84f7f0faaa4d5e51094501878bd23fe7"
    ),
    ".github/workflows/firmware-contract.yml": (
        "cd8f3a803cc3b4e10b5149b665f073744ef83a07d8e1d445cfe860b66a34b0fe"
    ),
}
EXPECTED_ASSET_PATHS = {
    "manual_procedure": "docs/development/p3b-bus-off-manual-test.md",
    "arm_gdb": "scripts/phase3/p3b_bus_off_arm.gdb",
    "retrigger_gdb": "scripts/phase3/p3b_bus_off_retrigger.gdb",
    "retrigger_verify_gdb": (
        "scripts/phase3/p3b_bus_off_retrigger_verify.gdb"
    ),
    "snapshot_gdb": "scripts/phase3/p3b_bus_off_snapshot.gdb",
}
EXPECTED_ASSET_HASHES = {
    "manual_procedure": (
        "34bfa39303511219fe9f559a94c1a4a4484128a9ffb091f04080a969bd18b75f"
    ),
    "arm_gdb": (
        "57ddc43b9764993b9160da5b15a90e81e7ab5478162e90beae8baeeabb781f5d"
    ),
    "retrigger_gdb": (
        "ba46bdfcf5caa656dda237d6cab13291659c98cda2de777d3d15a9306ad08ebf"
    ),
    "retrigger_verify_gdb": (
        "00b2637f0a666674f97d301ae49c6aa803a3778bb919141bcc66fe457ea74775"
    ),
    "snapshot_gdb": (
        "7f47be00f3f172285c0071c7c6bcdd458d4a5341e75527bfb2a9c4bebb170f6e"
    ),
}
EXPECTED_ATTEMPT_PATH = (
    "docs/evidence/phase3/P3B-bus-off-attempt-2026-08-15.json"
)
EXPECTED_ATTEMPT_SHA256 = (
    "83417a29c480a8029a8dde988c82e53797aea6bded158a891f2aaf58142345e4"
)
EXPECTED_ACCEPTANCE = {
    "automatic_recovery_attempts": 0,
    "bus_off_observed": 1,
    "cancel_timeout_observed": 0,
    "error_passive_observed": 1,
    "final_psr_bo": 1,
    "last_submit_status": 0,
    "max_tec_minimum": 128,
    "once_per_boot_consumed": 1,
    "post_cleanup_init": 1,
    "post_cleanup_pads_disconnected": 1,
    "post_cleanup_tx_pending": 0,
    "retrigger_rejected_count_delta": 1,
    "retrigger_tx_submit_count": 1,
    "result_state": "BUS_OFF_LATCHED",
    "run_nonce_matches_evidence": True,
    "tx_submit_count": 1,
    "warning_observed": 1,
}


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
        errors.append(f"invalid or missing {label}: {value}")
        return None
    if path.is_symlink() or not resolved.is_file():
        errors.append(f"{label} must be a regular repository file")
        return None
    return resolved


def read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def contains_pass_claim(value: object) -> bool:
    if isinstance(value, dict):
        return any(contains_pass_claim(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_pass_claim(item) for item in value)
    return isinstance(value, str) and value.upper() in {
        "PASS",
        "PASSED",
        "HIL_PASS",
        "COMPLETE",
    }


def validate(root: Path, manifest_relative: Path = DEFAULT_MANIFEST) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    manifest_path = repository_file(
        root, manifest_relative.as_posix(), "bus-off readiness manifest", errors
    )
    if manifest_path is None:
        return errors
    evidence = read_json(manifest_path, "bus-off readiness manifest", errors)

    expected_top = {
        "schema": 1,
        "evidence_id": "P3B-bus-off-fault-injection-readiness-2026-08-15",
        "phase": "P3B",
        "readiness": "READY_FOR_ACTIVE_FAULT_INJECTION",
        "qualification_status": "PARTIAL",
        "p4e_gate": "BLOCKED",
    }
    for name, expected in expected_top.items():
        if evidence.get(name) != expected:
            errors.append(f"bus-off readiness mismatch: {name}")

    actual_hil = evidence.get("actual_hil")
    expected_actual_hil = {
        "executed": True,
        "outcome": "TIMEOUT_CLEANED_NOT_BUS_OFF",
        "raw_evidence": {
            "path": EXPECTED_ATTEMPT_PATH,
            "sha256": EXPECTED_ATTEMPT_SHA256,
        },
        "status": "INCOMPLETE_PHYSICAL_FAULT_STIMULUS",
    }
    if actual_hil != expected_actual_hil:
        errors.append("actual bus-off HIL attempt evidence mismatch")
    if contains_pass_claim(actual_hil):
        errors.append("actual bus-off HIL PASS cannot be claimed")
    if isinstance(actual_hil, dict):
        attempt = actual_hil.get("raw_evidence")
        if isinstance(attempt, dict):
            attempt_path = repository_file(
                root,
                attempt.get("path"),
                "bus-off attempt evidence",
                errors,
            )
            if (
                attempt_path is not None
                and sha256_file(attempt_path) != EXPECTED_ATTEMPT_SHA256
            ):
                errors.append("bus-off attempt evidence SHA-256 mismatch")

    boundary = evidence.get("evidence_boundary")
    if not isinstance(boundary, dict):
        errors.append("bus-off evidence boundary is missing")
        boundary = {}
    if boundary.get("status") != "READY_FOR_ACTIVE_FAULT_INJECTION":
        errors.append(
            "bus-off evidence boundary must remain "
            "READY_FOR_ACTIVE_FAULT_INJECTION"
        )
    statement = boundary.get("statement")
    if (
        not isinstance(statement, str)
        or "TEC 128" not in statement
        or "did not reach bus-off" not in statement
        or "active bit/form/stuff-error injection" not in statement.lower()
        or "no PASS is claimed" not in statement
    ):
        errors.append("bus-off evidence boundary statement mismatch")

    source = evidence.get("source")
    if not isinstance(source, dict):
        errors.append("bus-off readiness source is missing")
        source = {}
    if source.get("commit") != "afbf243e1b0e433deb9fad946dab7d4beb3b026a":
        errors.append("bus-off readiness source commit mismatch")
    if source.get("dirty") is not True:
        errors.append("bus-off readiness must record dirty source")
    if source.get("hpm_sdk_commit") != (
        "88b01b43900d8c30844a1e5cdd3f3b7aff6db40e"
    ):
        errors.append("bus-off readiness HPM SDK commit mismatch")
    if source.get("toolchain") != (
        "riscv32-unknown-elf-gcc (gc891d8dc23e) 13.2.0"
    ):
        errors.append("bus-off readiness toolchain mismatch")
    source_files = source.get("files")
    if not isinstance(source_files, list):
        errors.append("bus-off readiness source files are missing")
        source_files = []
    observed_sources: dict[str, object] = {}
    for reference in source_files:
        if not isinstance(reference, dict):
            errors.append("invalid bus-off source reference")
            continue
        path_value = reference.get("path")
        if isinstance(path_value, str):
            observed_sources[path_value] = reference.get("sha256")
        source_path = repository_file(
            root, path_value, "bus-off source file", errors
        )
        if (
            source_path is not None
            and reference.get("sha256") != sha256_file(source_path)
        ):
            errors.append(f"bus-off source SHA-256 mismatch: {path_value}")
    if observed_sources != EXPECTED_SOURCE_HASHES:
        errors.append("bus-off immutable source set mismatch")

    assets = evidence.get("assets")
    if not isinstance(assets, dict):
        errors.append("bus-off readiness assets are missing")
        assets = {}
    asset_paths: dict[str, Path] = {}
    for name, expected_path in EXPECTED_ASSET_PATHS.items():
        reference = assets.get(name)
        if not isinstance(reference, dict) or reference.get("path") != expected_path:
            errors.append(f"bus-off readiness asset mismatch: {name}")
            continue
        asset_path = repository_file(
            root, reference.get("path"), f"bus-off {name}", errors
        )
        if asset_path is not None:
            asset_paths[name] = asset_path
            observed_hash = sha256_file(asset_path)
            if reference.get("sha256") != observed_hash:
                errors.append(f"bus-off asset SHA-256 mismatch: {name}")
            if EXPECTED_ASSET_HASHES.get(name) != observed_hash:
                errors.append(f"bus-off immutable asset mismatch: {name}")
    if set(assets) != set(EXPECTED_ASSET_PATHS):
        errors.append("bus-off immutable asset set mismatch")

    procedure_path = asset_paths.get("manual_procedure")
    if procedure_path is not None:
        procedure = procedure_path.read_text()
        for required in (
            "隔离台架",
            "禁止连接车辆",
            "不能仅依赖 ACK error",
            "PSR.BO",
            "最大值为 255",
            "automatic_recovery_attempts == 0",
            "cancel_timeout_observed == 0",
            "post_cleanup_pads_disconnected == 1",
            "retrigger",
            "P3B 仍为 `PARTIAL`",
        ):
            if required not in procedure:
                errors.append(f"manual procedure missing required safety text: {required}")

    arm_path = asset_paths.get("arm_gdb")
    if arm_path is not None:
        arm_lines = [
            line.strip()
            for line in arm_path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        command = "set var g_app_mcan0_bus_off_test_mailbox.command = 1"
        if not arm_lines or arm_lines[-1] != command:
            errors.append("bus-off arm command must be written last")
        if arm_lines.count(command) != 1:
            errors.append("bus-off arm command must be written exactly once")
        if any(line in {"continue", "c", "monitor go"} for line in arm_lines):
            errors.append("bus-off arm script must not automatically resume execution")
        arm_text = arm_path.read_text()
        for required in (
            "$p3b_run_nonce",
            "$_isvoid($p3b_run_nonce)",
            'error "',
            "define error",
            "quit 1",
            "g_app_mcan0_bus_off_test_result.magic",
            "g_app_mcan0_bus_off_test_result.once_per_boot_consumed",
            "g_app_mcan0_owner_state.initialized",
            "g_app_mcan0_owner_state.online",
            "g_app_mcan0_owner_state.mode",
            "g_app_mcan0_owner_state.tx_armed",
            "g_app_mcan0_owner_state.automatic_recovery_attempts",
            "0xF0280018",
            "0xF02800CC",
            "g_app_mcan0_bus_off_test_mailbox.reserved",
        ):
            if required not in arm_text:
                errors.append(f"bus-off arm script missing fail-closed check: {required}")
        if "0x20260815" in arm_text:
            errors.append("bus-off arm script must not contain a fixed run nonce")
        writes = [
            line
            for line in arm_lines
            if line.startswith("set var ")
        ]
        expected_writes = [
            "set var g_app_mcan0_bus_off_test_mailbox.magic = 0x424f4649",
            "set var g_app_mcan0_bus_off_test_mailbox.version = 2",
            (
                "set var g_app_mcan0_bus_off_test_mailbox.size = "
                "sizeof(g_app_mcan0_bus_off_test_mailbox)"
            ),
            (
                "set var g_app_mcan0_bus_off_test_mailbox.run_nonce = "
                "$p3b_run_nonce"
            ),
            (
                "set var g_app_mcan0_bus_off_test_mailbox.unlock_token = "
                "0x554e4c4b"
            ),
            (
                "set var g_app_mcan0_bus_off_test_mailbox.arm_token = "
                "0x41524d21"
            ),
            "set var g_app_mcan0_bus_off_test_mailbox.reserved = 0",
            command,
        ]
        if writes != expected_writes:
            errors.append("bus-off arm writes must match the fail-closed mailbox sequence")

    retrigger_path = asset_paths.get("retrigger_gdb")
    if retrigger_path is not None:
        retrigger = retrigger_path.read_text()
        for required in (
            "$p3b_retrigger_nonce",
            "$p3b_original_run_nonce",
            "$p3b_rejected_before",
            "define error",
            "quit 1",
            "g_app_mcan0_bus_off_test_result.state != 3",
            "g_app_mcan0_bus_off_test_result.once_per_boot_consumed != 1",
            "g_app_mcan0_bus_off_test_result.tx_submit_count != 1",
            "g_app_mcan0_owner_state.tx_armed != 0",
        ):
            if required not in retrigger:
                errors.append(
                    f"bus-off retrigger script missing fail-closed check: {required}"
                )
        retrigger_lines = [
            line.strip()
            for line in retrigger.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        command = "set var g_app_mcan0_bus_off_test_mailbox.command = 1"
        if not retrigger_lines or retrigger_lines[-1] != command:
            errors.append("bus-off retrigger command must be written last")
        if any(
            line in {"continue", "c", "monitor go"}
            for line in retrigger_lines
        ):
            errors.append("bus-off retrigger script must not automatically resume")

    retrigger_verify_path = asset_paths.get("retrigger_verify_gdb")
    if retrigger_verify_path is not None:
        retrigger_verify = retrigger_verify_path.read_text()
        for required in (
            "$_isvoid($p3b_original_run_nonce)",
            "$_isvoid($p3b_rejected_before)",
            "define error",
            "quit 1",
            (
                "g_app_mcan0_bus_off_test_result.rejected_command_count "
                "!= $p3b_rejected_before + 1"
            ),
            (
                "g_app_mcan0_bus_off_test_result.run_nonce "
                "!= $p3b_original_run_nonce"
            ),
            "g_app_mcan0_bus_off_test_result.state != 3",
            "g_app_mcan0_bus_off_test_result.tx_submit_count != 1",
            "g_app_mcan0_owner_state.tx_armed != 0",
            "g_app_mcan0_bus_off_test_mailbox.command != 0",
            "0xF02800CC",
        ):
            if required not in retrigger_verify:
                errors.append(
                    "bus-off retrigger verify script missing assertion: "
                    f"{required}"
                )
        retrigger_verify_lines = [
            line.strip()
            for line in retrigger_verify.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if any(
            line in {"continue", "c", "monitor go"}
            for line in retrigger_verify_lines
        ):
            errors.append(
                "bus-off retrigger verify script must not resume execution"
            )
        if any(line.startswith("set var ") for line in retrigger_verify_lines):
            errors.append("bus-off retrigger verify script must be read-only")

    snapshot_path = asset_paths.get("snapshot_gdb")
    if snapshot_path is not None:
        snapshot_text = snapshot_path.read_text()
        snapshot_lines = [
            line.strip()
            for line in snapshot_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        required_snapshot_commands = {
            "p g_app_mcan0_bus_off_test_mailbox",
            "p g_app_mcan0_bus_off_test_result",
            "p g_app_mcan0_owner_state",
            "p/x g_app_mcan0_bus_off_test_result.run_nonce",
            "p/x g_app_mcan0_bus_off_test_result.last_submit_status",
            "p/x g_app_mcan0_bus_off_test_result.tx_submit_count",
            "p/x g_app_mcan0_bus_off_test_result.warning_observed",
            "p/x g_app_mcan0_bus_off_test_result.error_passive_observed",
            "p/x g_app_mcan0_bus_off_test_result.bus_off_observed",
            "p/x g_app_mcan0_bus_off_test_result.final_protocol_status",
            "p/x g_app_mcan0_bus_off_test_result.post_cleanup_init",
            (
                "p/x g_app_mcan0_bus_off_test_result."
                "post_cleanup_tx_pending"
            ),
            (
                "p/x g_app_mcan0_bus_off_test_result."
                "post_cleanup_pads_disconnected"
            ),
            (
                "p/x g_app_mcan0_bus_off_test_result."
                "cancel_timeout_observed"
            ),
            (
                "p/x g_app_mcan0_bus_off_test_result."
                "automatic_recovery_attempts"
            ),
            "detach",
            "quit",
        }
        missing_snapshot = required_snapshot_commands - set(snapshot_lines)
        if missing_snapshot:
            errors.append("bus-off snapshot is missing required commands")
        if any(line.startswith("set var ") for line in snapshot_lines):
            errors.append("bus-off snapshot must be read-only")
        for required in (
            "$_isvoid($p3b_expected_run_nonce)",
            "define error",
            "quit 1",
            "g_app_mcan0_bus_off_test_result.magic != 0x424f4652",
            "g_app_mcan0_bus_off_test_result.version != 2",
            (
                "g_app_mcan0_bus_off_test_result.size != "
                "sizeof(g_app_mcan0_bus_off_test_result)"
            ),
            "g_app_mcan0_bus_off_test_result.state != 3",
            "g_app_mcan0_bus_off_test_result.tx_submit_count != 1",
            (
                "g_app_mcan0_bus_off_test_result.final_protocol_status "
                "& 0x80"
            ),
            (
                "g_app_mcan0_bus_off_test_result."
                "automatic_recovery_attempts != 0"
            ),
            (
                "g_app_mcan0_bus_off_test_result."
                "post_cleanup_pads_disconnected != 1"
            ),
            "0xF0280018",
            "0xF02800CC",
        ):
            if required not in snapshot_text:
                errors.append(
                    f"bus-off snapshot is missing assertion: {required}"
                )

    historical = evidence.get("historical_blocker")
    expected_blocker_path = (
        "docs/evidence/phase3/"
        "P3B-bus-off-fault-injection-blocker-2026-08-15.json"
    )
    if (
        not isinstance(historical, dict)
        or historical.get("path") != expected_blocker_path
        or historical.get("authority")
        != "HISTORICAL_SUPERSEDED_BY_THIS_READINESS"
    ):
        errors.append("historical bus-off blocker reference mismatch")
    else:
        blocker_path = repository_file(
            root, historical.get("path"), "historical bus-off blocker", errors
        )
        if blocker_path is not None:
            if historical.get("sha256") != sha256_file(blocker_path):
                errors.append("historical bus-off blocker SHA-256 mismatch")
            blocker = read_json(
                blocker_path, "historical bus-off blocker", errors
            )
            if (
                blocker.get("evidence_boundary", {}).get("status")
                != "BLOCKED_BY_MISSING_TEST_HOOK"
            ):
                errors.append("historical bus-off blocker content mismatch")

    acceptance = evidence.get("manual_acceptance")
    if not isinstance(acceptance, dict):
        errors.append("manual bus-off acceptance criteria are missing")
        acceptance = {}
    for name, expected in EXPECTED_ACCEPTANCE.items():
        if acceptance.get(name) != {"expected": expected, "status": "PENDING"}:
            errors.append(f"manual bus-off acceptance mismatch: {name}")
    if contains_pass_claim(acceptance):
        errors.append("manual bus-off acceptance cannot claim PASS before HIL")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    errors = validate(args.root, args.manifest)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS readiness=READY_FOR_ACTIVE_FAULT_INJECTION; "
        "attempt=TIMEOUT_CLEANED_NOT_BUS_OFF; P3B PARTIAL; P4E BLOCKED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
