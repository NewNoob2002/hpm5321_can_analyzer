#!/usr/bin/env python3
"""Collect a fail-closed joint RTOS/USB health snapshot after USB HIL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = DEFAULT_ROOT / "build/hpm5321-flash-release/build-manifest.json"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_HIL_TEST_IDS = {
    "T-USB-001A",
    "T-USB-005",
    "T-USB-006",
    "T-USB-007",
    "T-USB-008",
    "T-USB-010",
}

sys.path.insert(0, str(DEFAULT_ROOT))

from scripts.phase3.firmware_provenance import (  # noqa: E402
    verified_firmware_manifest,
)
from scripts.phase3.run_usb_hil import device_metadata  # noqa: E402


USB_FIELDS = (
    "magic",
    "version",
    "priority",
    "irq_requests",
    "initialized",
    "online",
    "connected",
    "configured",
    "generation",
    "connects",
    "resets",
    "disconnects",
    "configurations",
    "queue_sends",
    "queue_drops",
    "stale",
    "rx_completions",
    "tx_completions",
    "rx_bytes",
    "tx_bytes",
    "transfer_errors",
    "out_armed",
    "in_flight",
    "stack",
)
HEALTH_FIELDS = (
    "boot_magic",
    "boot_tick",
    "reset",
    "health_magic",
    "health_version",
    "heartbeat",
    "drops",
    "health_stack",
    "last_tick",
    "fault_magic",
    "fault_reason",
    "watchdog_magic",
    "watchdog_version",
    "required",
    "missing",
    "stall",
    "evaluations",
    "healthy",
    "alloc_magic",
    "alloc_version",
    "alloc_frozen",
    "allocations",
    "post_freeze_allocations",
)
HEX_FIELDS = {
    "magic",
    "boot_magic",
    "reset",
    "health_magic",
    "fault_magic",
    "watchdog_magic",
    "required",
    "missing",
    "stall",
    "alloc_magic",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _resolve(path: Path, root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repository_state(root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD").lower()
    if HEX_40.fullmatch(head) is None:
        raise RuntimeError("repository HEAD is not a 40-digit commit hash")
    status = _git(root, "status", "--short")
    return {"head": head, "dirty": bool(status), "status_short": status.splitlines()}


def load_hil_evidence(
    path: Path,
    root: Path,
    elf_sha256: str,
    reference_time: datetime | None = None,
    maximum_age_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read HIL evidence {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise RuntimeError(f"HIL evidence is not an object: {path}")
    completed_at = document.get("completed_at")
    if document.get("status") != "PASS" or not isinstance(completed_at, str):
        raise RuntimeError(f"HIL evidence is not a completed PASS: {path}")
    try:
        completed = datetime.fromisoformat(completed_at)
    except ValueError as exc:
        raise RuntimeError(f"HIL evidence completion time is invalid: {path}") from exc
    if completed.tzinfo is None:
        raise RuntimeError(f"HIL evidence completion time has no timezone: {path}")
    if reference_time is not None and maximum_age_seconds is not None:
        age_seconds = (reference_time - completed).total_seconds()
        if age_seconds < 0 or age_seconds > maximum_age_seconds:
            raise RuntimeError(
                f"HIL evidence is outside the post-HIL freshness window: {path}"
            )
    manifest = document.get("firmware_manifest")
    if not isinstance(manifest, dict) or manifest.get("elf_sha256") != elf_sha256:
        raise RuntimeError(
            f"HIL evidence firmware ELF does not match snapshot ELF: {path}"
        )
    test_id = document.get("test_id")
    test_references = document.get("test_references")
    if isinstance(test_id, str):
        identities = [test_id]
        boundary = document.get("evidence_boundary")
        verdicts = {
            test_id: boundary.get("verdict") if isinstance(boundary, dict) else None
        }
    elif isinstance(test_references, list) and all(
        isinstance(item, str) for item in test_references
    ):
        identities = test_references
        boundaries = document.get("evidence_boundaries")
        verdicts = {
            item: boundaries.get(item, {}).get("verdict")
            if isinstance(boundaries, dict)
            and isinstance(boundaries.get(item), dict)
            else None
            for item in identities
        }
    else:
        raise RuntimeError(f"HIL evidence has no valid test identity: {path}")
    if not identities or not set(identities) <= ALLOWED_HIL_TEST_IDS:
        raise RuntimeError(f"HIL evidence has an unsupported test identity: {path}")

    device = document.get("device")
    if not isinstance(device, dict):
        raise RuntimeError(f"HIL evidence has no device identity: {path}")
    device_identity = {
        "topology_path": device.get("topology_path"),
        "serial": device.get("serial"),
    }
    if not all(isinstance(value, str) and value for value in device_identity.values()):
        raise RuntimeError(f"HIL evidence device identity is incomplete: {path}")
    return {
        "path": _display_path(path, root),
        "sha256": _sha256(path),
        "test_references": identities,
        "qualification_verdicts": verdicts,
        "status": "PASS",
        "completed_at": completed_at,
        "elf_sha256": elf_sha256,
        "device": device_identity,
    }


def _parse_record(output: str, prefix: str, fields: tuple[str, ...]) -> dict[str, int]:
    records = re.findall(rf"^{re.escape(prefix)}(?:\s+.*)?$", output, re.MULTILINE)
    if len(records) != 1:
        raise RuntimeError(f"GDB output must contain exactly one {prefix} record")
    values: dict[str, int] = {}
    for token in records[0].split()[1:]:
        if "=" not in token:
            raise RuntimeError(f"malformed {prefix} token: {token}")
        name, value = token.split("=", 1)
        if name in values or name not in fields:
            raise RuntimeError(f"unexpected or duplicate {prefix} field: {name}")
        try:
            values[name] = int(value, 16 if name in HEX_FIELDS else 10)
        except ValueError as exc:
            raise RuntimeError(f"invalid {prefix} value for {name}") from exc
    missing = set(fields) - values.keys()
    if missing:
        raise RuntimeError(
            f"{prefix} record is missing fields: {', '.join(sorted(missing))}"
        )
    return values


def parse_snapshot(output: str) -> dict[str, dict[str, int]]:
    return {
        "usb_owner": _parse_record(output, "P3A_USB", USB_FIELDS),
        "rtos_health": _parse_record(output, "P3A_HEALTH", HEALTH_FIELDS),
    }


def validate_snapshot(snapshot: dict[str, dict[str, int]], minimum_stack: int) -> None:
    usb = snapshot["usb_owner"]
    health = snapshot["rtos_health"]
    required_usb = {
        "magic": 0x5553424F,
        "version": 1,
        "priority": 4,
        "initialized": 1,
        "online": 1,
        "connected": 1,
        "configured": 1,
        "out_armed": 1,
        "in_flight": 0,
    }
    for field, expected in required_usb.items():
        if usb[field] != expected:
            raise RuntimeError(f"USB owner invariant failed: {field} != {expected}")
    for field in (
        "irq_requests",
        "configurations",
        "rx_completions",
        "tx_completions",
    ):
        if usb[field] <= 0:
            raise RuntimeError(f"USB owner invariant failed: {field} did not advance")
    for field in ("queue_drops", "transfer_errors"):
        if usb[field] != 0:
            raise RuntimeError(f"USB owner invariant failed: {field} is nonzero")
    if usb["rx_completions"] != usb["tx_completions"]:
        raise RuntimeError("USB owner RX/TX completion counts do not reconcile")
    if usb["rx_bytes"] <= 0 or usb["rx_bytes"] != usb["tx_bytes"]:
        raise RuntimeError("USB owner RX/TX byte counts do not reconcile")
    if usb["stack"] < minimum_stack:
        raise RuntimeError("USB owner stack watermark is below the threshold")

    expected_health = {
        "boot_magic": 0x424F4F54,
        "health_magic": 0x484C5448,
        "health_version": 1,
        "fault_magic": 0,
        "fault_reason": 0,
        "watchdog_magic": 0x57444756,
        "watchdog_version": 1,
        "required": 0x7,
        "missing": 0,
        "stall": 0,
        "alloc_magic": 0x414C4C43,
        "alloc_version": 1,
        "alloc_frozen": 1,
        "post_freeze_allocations": 0,
    }
    for field, expected in expected_health.items():
        if health[field] != expected:
            raise RuntimeError(f"RTOS health invariant failed: {field} != {expected}")
    if health["heartbeat"] <= 0 or health["last_tick"] <= health["boot_tick"]:
        raise RuntimeError("RTOS heartbeat has not advanced since boot")
    if health["drops"] != 0:
        raise RuntimeError("RTOS health queue dropped an event")
    if health["health_stack"] < minimum_stack:
        raise RuntimeError("health task stack watermark is below the threshold")
    if health["evaluations"] <= 0 or health["healthy"] != health["evaluations"]:
        raise RuntimeError("watchdog evaluation history is not entirely healthy")


def _sample_target(gdb: Path, elf: Path, port: int) -> dict[str, dict[str, int]]:
    usb_format = " ".join(
        f"{name}=%08x"
        if name == "magic"
        else f"{name}=%llu"
        if name in {"rx_bytes", "tx_bytes"}
        else f"{name}=%u"
        for name in USB_FIELDS
    )
    usb_values = (
        "g_app_usb_owner_state.magic, g_app_usb_owner_state.version, "
        "g_app_usb_owner_state.irq_priority, g_app_usb_owner_state.irq_enable_requests, "
        "g_app_usb_owner_state.initialized, g_app_usb_owner_state.online, "
        "g_app_usb_owner_state.connected, g_app_usb_owner_state.configured, "
        "g_app_usb_owner_state.generation, g_app_usb_owner_state.connect_count, "
        "g_app_usb_owner_state.reset_count, g_app_usb_owner_state.disconnect_count, "
        "g_app_usb_owner_state.configured_count, g_app_usb_owner_state.queue_send_count, "
        "g_app_usb_owner_state.queue_drops, g_app_usb_owner_state.stale_events, "
        "g_app_usb_owner_state.rx_completions, g_app_usb_owner_state.tx_completions, "
        "g_app_usb_owner_state.rx_bytes, g_app_usb_owner_state.tx_bytes, "
        "g_app_usb_owner_state.transfer_errors, g_app_usb_owner_state.out_armed, "
        "g_app_usb_owner_state.in_flight, g_app_usb_owner_state.stack_high_watermark"
    )
    health_format = " ".join(
        f"{name}=%08x"
        if name in HEX_FIELDS
        else f"{name}=%llu"
        if name in {"boot_tick", "last_tick"}
        else f"{name}=%u"
        for name in HEALTH_FIELDS
    )
    health_values = (
        "g_app_boot_state.magic, g_app_boot_state.boot_timestamp, g_app_boot_state.reset_flags, "
        "g_app_health_state.magic, g_app_health_state.version, g_app_health_state.heartbeat_count, "
        "g_app_health_state.timer_queue_drops, g_app_health_state.stack_high_watermark, "
        "g_app_health_state.last_heartbeat_tick, g_app_fault_state.magic, g_app_fault_state.reason, "
        "g_app_watchdog_state.magic, g_app_watchdog_state.version, g_app_watchdog_state.required_mask, "
        "g_app_watchdog_state.missing_mask, g_app_watchdog_state.test_stall_mask, "
        "g_app_watchdog_state.evaluation_count, g_app_watchdog_state.healthy_evaluation_count, "
        "g_app_allocation_state.magic, g_app_allocation_state.version, g_app_allocation_state.frozen, "
        "g_app_allocation_state.allocation_calls, g_app_allocation_state.post_freeze_allocation_calls"
    )
    command = [
        str(gdb),
        "-q",
        str(elf),
        "-batch",
        "-ex",
        "set pagination off",
        "-ex",
        f"target remote localhost:{port}",
        "-ex",
        "monitor halt",
        "-ex",
        f'printf "P3A_USB {usb_format}\\n", {usb_values}',
        "-ex",
        f'printf "P3A_HEALTH {health_format}\\n", {health_values}',
        "-ex",
        "monitor go",
        "-ex",
        "detach",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"GDB snapshot failed: {output.strip()}")
    return parse_snapshot(output)


def collect(
    args: argparse.Namespace,
    sampler: Callable[[Path, Path, int], dict[str, dict[str, int]]] = _sample_target,
) -> int:
    root = args.root.resolve()
    output = _resolve(args.output, root)
    elf = _resolve(args.elf, root)
    manifest_path = _resolve(args.firmware_manifest, root)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "evidence_id": "P3A-POST-HIL-HEALTH",
        "test_references": [],
        "status": "RUNNING",
        "evidence_boundary": {
            "verdict": "PENDING",
            "covered": "one atomic post-HIL debugger halt jointly sampling USB owner and RTOS health invariants",
            "not_covered": (
                "independent qualification of any referenced USB workload, RTOS "
                "duration, Windows, protocol/session, or CAN behavior; linkage is a "
                "fresh host-side ELF/device association rather than an on-device run nonce"
            ),
        },
        "status_semantics": (
            "PASS only proves the recorded post-HIL joint health snapshot and its "
            "linkage to completed HIL evidence"
        ),
        "started_at": _now(),
        "operator": args.operator,
        "minimum_stack_words": args.minimum_stack_words,
        "maximum_hil_age_seconds": args.maximum_hil_age_seconds,
        "probe_serial": args.probe_serial,
        "target_device": args.device,
        "elf": _display_path(elf, root),
        "elf_sha256": "",
        "hil_evidence": [],
    }
    server: subprocess.Popen[bytes] | None = None
    try:
        if not elf.is_file():
            raise RuntimeError(f"ELF does not exist: {elf}")
        evidence["elf_sha256"] = _sha256(elf)
        firmware = verified_firmware_manifest(manifest_path, root)
        if firmware["elf_sha256"] != evidence["elf_sha256"]:
            raise RuntimeError("sampled ELF does not match the verified firmware manifest")
        evidence["firmware_manifest"] = firmware
        evidence["repository"] = repository_state(root)
        if not args.hil_evidence:
            raise RuntimeError("at least one completed HIL evidence file is required")
        reference_time = datetime.now(timezone.utc)
        evidence["hil_evidence"] = [
            load_hil_evidence(
                _resolve(path, root),
                root,
                evidence["elf_sha256"],
                reference_time,
                args.maximum_hil_age_seconds,
            )
            for path in args.hil_evidence
        ]
        evidence["test_references"] = sorted(
            {
                test_id
                for item in evidence["hil_evidence"]
                for test_id in item["test_references"]
            }
        )
        current_device = device_metadata(args.sysfs_root)
        current_identity = {
            "topology_path": current_device["topology_path"],
            "serial": current_device["serial"],
        }
        if any(
            item["device"] != current_identity for item in evidence["hil_evidence"]
        ):
            raise RuntimeError("current USB device identity does not match HIL evidence")
        evidence["device"] = current_device
        _write_evidence(output, evidence)

        server = subprocess.Popen(
            [
                str(args.gdb_server),
                "-select",
                f"USB={args.probe_serial}",
                "-device",
                args.device,
                "-if",
                "JTAG",
                "-speed",
                str(args.jtag_khz),
                "-port",
                str(args.port),
                "-swoport",
                str(args.port + 1),
                "-telnetport",
                str(args.port + 2),
                "-silent",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(args.server_start_seconds)
        if server.poll() is not None:
            raise RuntimeError("J-Link GDB server exited before sampling")
        snapshot = sampler(args.gdb, elf, args.port)
        validate_snapshot(snapshot, args.minimum_stack_words)
        evidence["snapshot"] = {"collected_at": _now(), **snapshot}
        evidence["status"] = "PASS"
        evidence["evidence_boundary"]["verdict"] = "PASS"
        evidence["completed_at"] = _now()
        _write_evidence(output, evidence)
        print(
            f"PASS P3A post-HIL health elf_sha256={evidence['elf_sha256']} "
            f"evidence={output}"
        )
        return 0
    except (OSError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence["status"] = "FAIL"
        evidence["evidence_boundary"]["verdict"] = "NOT_QUALIFIED"
        evidence["completed_at"] = _now()
        evidence["failure"] = str(exc)
        _write_evidence(output, evidence)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--elf",
        type=Path,
        default=DEFAULT_ROOT / "build/hpm5321-flash-release/output/demo.elf",
    )
    parser.add_argument("--firmware-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--hil-evidence", action="append", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_ROOT
        / "docs/evidence/phase3/P3A-post-HIL-health-current.json",
    )
    parser.add_argument("--minimum-stack-words", type=int, default=128)
    parser.add_argument("--maximum-hil-age-seconds", type=float, default=300.0)
    parser.add_argument(
        "--sysfs-root", type=Path, default=Path("/sys/bus/usb/devices")
    )
    parser.add_argument("--server-start-seconds", type=float, default=1.0)
    parser.add_argument("--probe-serial", default="607000454")
    parser.add_argument("--device", default="HPM5321xCFx")
    parser.add_argument("--jtag-khz", type=int, default=4000)
    parser.add_argument("--port", type=int, default=2331)
    parser.add_argument("--gdb", type=Path, default=Path("riscv32-unknown-elf-gdb"))
    parser.add_argument(
        "--gdb-server", type=Path, default=Path("JLinkGDBServerCLExe")
    )
    parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    args = parser.parse_args()
    for name in (
        "minimum_stack_words",
        "maximum_hil_age_seconds",
        "server_start_seconds",
        "jtag_khz",
        "port",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
