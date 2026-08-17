#!/usr/bin/env python3
"""Validate the P3B active bus-off HIL preflight without touching hardware."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREFLIGHT = Path(
    "docs/evidence/phase3/P3B-active-bus-off-hil-preflight-2026-08-17.json"
)
SOURCE_COMMIT = "a4e310f79c40d1324a642c76d46403b927aa2a07"
SDK_COMMIT = "88b01b43900d8c30844a1e5cdd3f3b7aff6db40e"
TOOLCHAIN = "riscv32-unknown-elf-gcc (gc891d8dc23e) 13.2.0"
DEBUG_ELF = "880993181c64c5ede0dfd2d79a1a6d67f8257affae11f297cb6ecbf1a6ed64be"
DEBUG_BIN = "36c9d9b8ae4e2ed1f8430a66d5f61580e15d86887d48704d2fad1223ffe02b87"
DEBUG_MAP = "d5ffa8d400634ae36741ad31d9e58dd22f324904ca99ff332cbb85bec4a36bea"
DEBUG_MANIFEST = "04fa7b72af3d465055b31a9e4a2647614b508ccad1c68f21f6f7c7a6000277ba"

EXPECTED_SOFTWARE_IDENTITY = {
    "source_commit": SOURCE_COMMIT,
    "source_dirty": False,
    "sdk_commit": SDK_COMMIT,
    "toolchain": TOOLCHAIN,
    "cmake_preset": "hpm5321-ram-debug-bus-off",
    "build_options": {
        "CMAKE_BUILD_TYPE": "Debug",
        "HPM_BUILD_TYPE": "ram",
        "APP_MCAN0_BUS_OFF_TEST_HOOK": True,
        "APP_FAULT_INJECT_REASON": 0,
        "APP_MCAN_BITRATE": 1_000_000,
    },
    "selected_load_artifact": "ELF",
    "debug_elf_sha256": DEBUG_ELF,
    "debug_bin_sha256": DEBUG_BIN,
    "debug_map_sha256": DEBUG_MAP,
    "debug_manifest_sha256": DEBUG_MANIFEST,
    "same_sha_ci_complete": True,
}

EXPECTED_CI = [
    {
        "workflow": "Planning Contract",
        "run_id": 31952850072,
        "head_sha": SOURCE_COMMIT,
        "event": "push",
        "conclusion": "success",
    },
    {
        "workflow": "C Protocol",
        "run_id": 31953321449,
        "head_sha": SOURCE_COMMIT,
        "event": "workflow_dispatch",
        "conclusion": "success",
    },
    {
        "workflow": "Host Rust",
        "run_id": 31953322054,
        "head_sha": SOURCE_COMMIT,
        "event": "workflow_dispatch",
        "conclusion": "success",
    },
    {
        "workflow": "Firmware Contract",
        "run_id": 31953325395,
        "head_sha": SOURCE_COMMIT,
        "event": "workflow_dispatch",
        "conclusion": "success",
    },
]

EXPECTED_GDB_FAULT_INJECTION_POLICY = {
    "mailbox_arm_after_separate_hardware_authorization_allowed": True,
    "write_result_state_or_latch_for_hardware_pass_allowed": False,
    "write_psr_or_ecr_for_hardware_pass_allowed": False,
    "ack_suppression_only_accepted_for_hardware_pass": False,
    "synthetic_software_path_test_may_be_planned_separately": True,
    "synthetic_evidence_class": "SOFTWARE_ONLY_NOT_HARDWARE_BUS_OFF",
    "decision": "NOT_A_REPLACEMENT_FOR_ACTIVE_FAULT_INJECTOR",
}

BLOCK_BENCH = "isolated bench and vehicle/gateway disconnection are not confirmed"
BLOCK_ESTOP = "emergency stop or power-cut method is not approved"
BLOCK_DUT = "DUT identity and target voltage are missing"
BLOCK_PROBE = "debug probe identity and firmware version are missing"
BLOCK_ANALYZER = (
    "CAN analyzer identity, mode, version, and timestamp resolution are missing"
)
BLOCK_INJECTOR = (
    "active fault injector identity, supported injection type, operating limits, "
    "and stop condition are missing"
)
BLOCK_BUS = (
    "bus sample point, mode, termination, common ground, and idle voltage are not "
    "confirmed"
)
BLOCK_OBSERVATION = "post-latch observation duration is not approved"
BLOCK_RUNS = (
    "three independent run IDs, nonces, paths, wiring records, and equipment "
    "records are not assigned"
)
BLOCK_RAW = "raw GDB and analyzer capture availability is not confirmed"
BLOCK_APPROVALS = (
    "operator, distinct independent reviewer, and project/safety approver "
    "approvals are missing"
)


def nonempty(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None


def positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def assigned_runs(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    required_text = (
        "run_id",
        "log_directory",
        "gdb_transcript",
        "analyzer_raw_file",
        "wiring_record",
        "equipment_identity_record",
    )
    unique_fields = (
        "run_id",
        "nonce",
        "log_directory",
        "gdb_transcript",
        "analyzer_raw_file",
    )
    collected: dict[str, list[object]] = {name: [] for name in unique_fields}
    for run in value:
        if not isinstance(run, dict):
            return False
        if any(not nonempty(run.get(name)) for name in required_text):
            return False
        nonce = run.get("nonce")
        if isinstance(nonce, bool) or not isinstance(nonce, (int, str)):
            return False
        if nonce == 0 or (isinstance(nonce, str) and not nonce.strip()):
            return False
        if run.get("pre_run_reboot_or_power_cycle_required") is not True:
            return False
        if run.get("firmware_elf_sha256") != DEBUG_ELF:
            return False
        if run.get("firmware_bin_sha256") != DEBUG_BIN:
            return False
        for name in unique_fields:
            collected[name].append(run.get(name))
    return all(len(set(values)) == 3 for values in collected.values())


def readiness_blockers(preflight: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    bench = preflight.get("bench") if isinstance(preflight.get("bench"), dict) else {}
    if not (
        bench.get("isolated_bench_confirmed") is True
        and bench.get("vehicle_connected") is False
        and bench.get("production_gateway_connected") is False
    ):
        blockers.append(BLOCK_BENCH)
    if not nonempty(bench.get("emergency_stop_or_power_cut_method")):
        blockers.append(BLOCK_ESTOP)

    dut = preflight.get("dut") if isinstance(preflight.get("dut"), dict) else {}
    if not (
        all(
            nonempty(dut.get(name))
            for name in ("model", "hardware_revision", "serial_number")
        )
        and positive_number(dut.get("target_voltage_v"))
    ):
        blockers.append(BLOCK_DUT)

    probe = (
        preflight.get("debug_probe")
        if isinstance(preflight.get("debug_probe"), dict)
        else {}
    )
    if not all(
        nonempty(probe.get(name))
        for name in ("model", "serial_number", "firmware_version")
    ):
        blockers.append(BLOCK_PROBE)

    analyzer = (
        preflight.get("can_analyzer")
        if isinstance(preflight.get("can_analyzer"), dict)
        else {}
    )
    if not all(
        nonempty(analyzer.get(name))
        for name in (
            "model",
            "serial_number",
            "firmware_or_software_version",
            "mode",
            "timestamp_resolution",
        )
    ):
        blockers.append(BLOCK_ANALYZER)

    injector = (
        preflight.get("active_fault_injector")
        if isinstance(preflight.get("active_fault_injector"), dict)
        else {}
    )
    supported = injector.get("supported_injection_types")
    selected = injector.get("selected_injection_type")
    if not (
        injector.get("present") is True
        and all(
            nonempty(injector.get(name))
            for name in (
                "model",
                "serial_number",
                "firmware_or_software_version",
                "operating_limits",
                "emergency_stop_condition",
            )
        )
        and isinstance(supported, list)
        and bool(supported)
        and all(nonempty(item) for item in supported)
        and selected in supported
    ):
        blockers.append(BLOCK_INJECTOR)

    bus = preflight.get("bus") if isinstance(preflight.get("bus"), dict) else {}
    sample_point = bus.get("sample_point_percent")
    if not (
        bus.get("bitrate_bits_per_second") == 1_000_000
        and positive_number(sample_point)
        and sample_point <= 100
        and isinstance(bus.get("fd_enabled"), bool)
        and positive_number(bus.get("termination_ohms"))
        and bus.get("common_ground_confirmed") is True
        and nonempty(bus.get("measured_idle_voltage"))
    ):
        blockers.append(BLOCK_BUS)

    execution = (
        preflight.get("execution")
        if isinstance(preflight.get("execution"), dict)
        else {}
    )
    duration = execution.get("post_latch_observation_seconds")
    if not (
        isinstance(duration, int) and not isinstance(duration, bool) and duration > 0
    ):
        blockers.append(BLOCK_OBSERVATION)
    if not assigned_runs(preflight.get("runs")):
        blockers.append(BLOCK_RUNS)
    if not (
        execution.get("raw_gdb_capture_available") is True
        and execution.get("raw_analyzer_capture_available") is True
    ):
        blockers.append(BLOCK_RAW)

    operator = (
        preflight.get("operator")
        if isinstance(preflight.get("operator"), dict)
        else {}
    )
    reviewer = (
        preflight.get("independent_reviewer")
        if isinstance(preflight.get("independent_reviewer"), dict)
        else {}
    )
    safety_approver = (
        preflight.get("project_safety_approver")
        if isinstance(preflight.get("project_safety_approver"), dict)
        else {}
    )
    if not (
        nonempty(operator.get("identity"))
        and operator.get("approval") is True
        and nonempty(reviewer.get("identity"))
        and reviewer.get("approval") is True
        and reviewer.get("distinct_from_operator") is True
        and reviewer.get("identity") != operator.get("identity")
        and nonempty(safety_approver.get("identity"))
        and safety_approver.get("approval") is True
    ):
        blockers.append(BLOCK_APPROVALS)
    return blockers


def validate(root: Path, preflight_path: Path = DEFAULT_PREFLIGHT) -> list[str]:
    errors: list[str] = []
    path = preflight_path if preflight_path.is_absolute() else root / preflight_path
    try:
        path.resolve(strict=True).relative_to(root.resolve())
    except (FileNotFoundError, ValueError):
        return [f"invalid or missing preflight path: {preflight_path}"]
    if path.is_symlink() or not path.is_file():
        return ["preflight must be a regular repository file"]
    try:
        preflight = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid preflight JSON: {exc}"]
    if not isinstance(preflight, dict):
        return ["preflight root must be an object"]

    expected_header = {
        "schema": 1,
        "phase": "P3B",
        "purpose": "active_bus_off_hil_preflight_only",
        "hardware_execution_authorized": False,
    }
    for name, expected in expected_header.items():
        if preflight.get(name) != expected:
            errors.append(f"preflight header mismatch: {name}")
    if preflight.get("software_identity") != EXPECTED_SOFTWARE_IDENTITY:
        errors.append("preflight software identity mismatch")
    if preflight.get("ci") != EXPECTED_CI:
        errors.append("preflight same-SHA CI matrix mismatch")
    if (
        preflight.get("gdb_fault_injection_policy")
        != EXPECTED_GDB_FAULT_INJECTION_POLICY
    ):
        errors.append("preflight GDB fault-injection policy mismatch")

    execution = preflight.get("execution")
    fixed_execution = {
        "independent_runs": 3,
        "reboot_or_power_cycle_between_runs": True,
        "unique_nonce_per_run": True,
        "unique_log_directory_per_run": True,
        "same_firmware_sha_for_all_runs": True,
        "cleanup_required_per_run": True,
    }
    if not isinstance(execution, dict):
        errors.append("preflight execution record is missing")
    else:
        for name, expected in fixed_execution.items():
            if execution.get(name) != expected:
                errors.append(f"preflight execution invariant mismatch: {name}")
        for name in (
            "cleanup_confirmed_per_run",
            "raw_gdb_capture_available",
            "raw_analyzer_capture_available",
        ):
            if not isinstance(execution.get(name), bool):
                errors.append(f"preflight execution flag must be boolean: {name}")

    runs = preflight.get("runs")
    if not isinstance(runs, list) or len(runs) != 3:
        errors.append("preflight must define exactly three runs")
    else:
        result_flags = (
            "pre_run_reboot_or_power_cycle_confirmed",
            "trigger_verified",
            "latch_verified",
            "no_recovery_verified",
            "cleanup_verified",
            "retrigger_rejection_verified",
        )
        for index, run in enumerate(runs, start=1):
            if not isinstance(run, dict):
                errors.append(f"preflight run {index} must be an object")
                continue
            for name in result_flags:
                if not isinstance(run.get(name), bool):
                    errors.append(
                        f"preflight run {index} flag must be boolean: {name}"
                    )
            for name in ("started_at_utc", "ended_at_utc"):
                if run.get(name) is not None and not nonempty(run.get(name)):
                    errors.append(
                        f"preflight run {index} timestamp is invalid: {name}"
                    )

    blockers = readiness_blockers(preflight)
    expected_decision = (
        "READY_FOR_HIL_PREFLIGHT_APPROVAL"
        if not blockers
        else "BLOCKED_FOR_HIL_PREFLIGHT"
    )
    if preflight.get("decision") != expected_decision:
        errors.append("preflight decision does not match blockers")
    if preflight.get("approved") is not (not blockers):
        errors.append("preflight approval does not match blockers")
    if preflight.get("blockers") != blockers:
        errors.append("preflight blocker list does not match unresolved fields")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preflight", nargs="?", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root, args.preflight)
    if errors:
        raise SystemExit("; ".join(errors))
    path = args.preflight if args.preflight.is_absolute() else root / args.preflight
    data = json.loads(path.read_text())
    blockers = readiness_blockers(data)
    if args.require_ready and blockers:
        raise SystemExit("BLOCKED_FOR_HIL_PREFLIGHT: " + "; ".join(blockers))
    print(f"PASS decision={data['decision']} blockers={len(blockers)}")


if __name__ == "__main__":
    main()
