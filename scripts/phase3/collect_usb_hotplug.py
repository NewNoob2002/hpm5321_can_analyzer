#!/usr/bin/env python3
"""Collect T-USB-007 physical disconnect/reconnect evidence on Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = DEFAULT_ROOT / "build/hpm5321-flash-release/build-manifest.json"
sys.path.insert(0, str(DEFAULT_ROOT))

from scripts.phase3.firmware_provenance import (  # noqa: E402
    verified_firmware_manifest,
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def find_usb_devices(sysfs_root: Path, vid: str, pid: str) -> list[Path]:
    matches: list[Path] = []
    for candidate in sysfs_root.iterdir():
        if (
            _read_text(candidate / "idVendor").casefold() == vid.casefold()
            and _read_text(candidate / "idProduct").casefold() == pid.casefold()
        ):
            matches.append(candidate)
    return sorted(matches)


def usb_device_node(
    device: Path, devfs_root: Path = Path("/dev/bus/usb")
) -> Path | None:
    try:
        bus = int(_read_text(device / "busnum"))
        number = int(_read_text(device / "devnum"))
    except ValueError:
        return None
    return devfs_root / f"{bus:03d}" / f"{number:03d}"


def usb_identity(device: Path) -> dict[str, str]:
    return {
        "topology_path": device.name,
        "manufacturer": _read_text(device / "manufacturer"),
        "product": _read_text(device / "product"),
        "serial": _read_text(device / "serial"),
        "speed_mbps": _read_text(device / "speed"),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _run_smoke(executable: Path, byte_count: int) -> dict[str, Any]:
    result = subprocess.run(
        [str(executable), "--bytes", str(byte_count)],
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _run_smoke_with_retry(
    executable: Path,
    byte_count: int,
    timeout_seconds: float,
    retry_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + timeout_seconds
    attempts: list[dict[str, Any]] = []
    while True:
        smoke = _run_smoke(executable, byte_count)
        attempts.append(smoke)
        now = time.monotonic()
        if smoke["exit_code"] == 0 or now >= deadline:
            return {
                **smoke,
                "attempt_count": len(attempts),
                "attempts": attempts,
                "recovery_ms": round((now - started) * 1000.0, 3),
            }
        time.sleep(retry_ms / 1000.0)


def collect(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    executable = args.smoke_executable
    if not executable.is_absolute():
        executable = root / executable
    executable = executable.resolve()
    output = args.output
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    manifest_path = args.firmware_manifest
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest_path = manifest_path.resolve()

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "test_id": "T-USB-007",
        "evidence_boundary": {
            "verdict": "PENDING",
            "covered": "100 physical disconnect/reconnect cycles, udev node access, and an exact 1 MiB recovery echo after every cycle",
            "not_covered": "Windows PnP, FS fallback, endpoint HALT, protocol/session, or CAN data-plane behavior",
        },
        "status_semantics": "PASS qualifies T-USB-007 for the recorded physical-cable cycles and recovery echo only",
        "status": "RUNNING",
        "started_at": _now(),
        "operator": args.operator,
        "disconnect_method": "physical-cable",
        "vid": args.vid.lower(),
        "pid": args.pid.lower(),
        "required_cycles": args.cycles,
        "completed_cycles": 0,
        "minimum_disconnect_ms": args.minimum_disconnect_ms,
        "recovery_timeout_seconds": args.recovery_timeout_seconds,
        "smoke_retry_ms": args.smoke_retry_ms,
        "smoke_bytes": args.smoke_bytes,
        "smoke_executable": _display_path(executable, root),
        "smoke_sha256": "",
        "initial_smoke": {},
        "cycles": [],
    }

    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError(f"smoke executable is missing or not executable: {executable}")
        evidence["smoke_sha256"] = _sha256(executable)
        evidence["repository"] = {
            "head": _git_value(root, "rev-parse", "HEAD"),
            "dirty": bool(_git_value(root, "status", "--short")),
        }
        evidence["firmware_manifest"] = verified_firmware_manifest(
            manifest_path, root
        )

        deadline = time.monotonic() + args.overall_timeout_seconds
        print(
            f"Waiting for USB {args.vid}:{args.pid}; connect it before starting "
            f"{args.cycles} physical cable cycles.",
            flush=True,
        )
        devices: list[Path] = []
        while time.monotonic() < deadline:
            devices = find_usb_devices(args.sysfs_root, args.vid, args.pid)
            if len(devices) == 1:
                break
            if len(devices) > 1:
                raise RuntimeError("more than one matching USB device is present")
            time.sleep(args.poll_ms / 1000.0)
        if len(devices) != 1:
            raise RuntimeError("timed out waiting for the initial USB connection")

        identity = usb_identity(devices[0])
        if not identity["serial"]:
            raise RuntimeError("USB serial is missing; device identity is not qualifiable")
        evidence["device"] = identity
        evidence["topology_path"] = identity["topology_path"]
        device_node = usb_device_node(devices[0], args.devfs_root)
        evidence["device_node"] = str(device_node) if device_node else None
        evidence["device_node_readable"] = bool(
            device_node and os.access(device_node, os.R_OK)
        )
        evidence["device_node_writable"] = bool(
            device_node and os.access(device_node, os.W_OK)
        )
        if not (
            evidence["device_node_readable"] and evidence["device_node_writable"]
        ):
            raise RuntimeError(
                f"USB device node is not readable/writable: {device_node}; "
                "install config/udev/99-hpm5321-can-analyzer.rules and reconnect"
            )
        evidence["initial_smoke"] = _run_smoke_with_retry(
            executable,
            args.smoke_bytes,
            args.recovery_timeout_seconds,
            args.smoke_retry_ms,
        )
        if evidence["initial_smoke"]["exit_code"] != 0:
            raise RuntimeError("initial recovery smoke failed")
        _write_evidence(output, evidence)

        state = "present"
        disconnected_at = 0.0
        disconnected_wall = ""
        cycle_number = 1
        print("Initial smoke passed. Physically unplug and reconnect the cable.", flush=True)
        while cycle_number <= args.cycles and time.monotonic() < deadline:
            devices = find_usb_devices(args.sysfs_root, args.vid, args.pid)
            if len(devices) > 1:
                raise RuntimeError("more than one matching USB device is present")
            present = len(devices) == 1
            now = time.monotonic()
            if state == "present" and not present:
                disconnected_at = now
                disconnected_wall = _now()
                state = "absent"
            elif state == "absent" and present:
                absent_ms = (now - disconnected_at) * 1000.0
                if absent_ms < args.minimum_disconnect_ms:
                    raise RuntimeError(
                        f"cycle {cycle_number} disconnect was only {absent_ms:.1f} ms"
                    )
                reconnected_at = _now()
                smoke = _run_smoke_with_retry(
                    executable,
                    args.smoke_bytes,
                    args.recovery_timeout_seconds,
                    args.smoke_retry_ms,
                )
                ready_devices = find_usb_devices(args.sysfs_root, args.vid, args.pid)
                ready_device = ready_devices[0] if len(ready_devices) == 1 else None
                ready_identity = usb_identity(ready_device) if ready_device else None
                device_node = (
                    usb_device_node(ready_device, args.devfs_root)
                    if ready_device
                    else None
                )
                cycle = {
                    "cycle": cycle_number,
                    "disconnected_at": disconnected_wall,
                    "reconnected_at": reconnected_at,
                    "recovery_completed_at": _now(),
                    "disconnect_ms": round(absent_ms, 3),
                    "topology_path": (
                        ready_device.name if ready_device else devices[0].name
                    ),
                    "device": ready_identity,
                    "device_node": str(device_node) if device_node else None,
                    "device_node_readable": bool(
                        device_node and os.access(device_node, os.R_OK)
                    ),
                    "device_node_writable": bool(
                        device_node and os.access(device_node, os.W_OK)
                    ),
                    "recovery_smoke": smoke,
                }
                evidence["cycles"].append(cycle)
                if ready_identity != identity:
                    raise RuntimeError(
                        f"cycle {cycle_number} USB identity changed after reconnect"
                    )
                if not (
                    cycle["device_node_readable"]
                    and cycle["device_node_writable"]
                ):
                    raise RuntimeError(
                        f"cycle {cycle_number} USB device node is not readable/writable: "
                        f"{device_node}"
                    )
                if smoke["exit_code"] != 0:
                    raise RuntimeError(f"cycle {cycle_number} recovery smoke failed")
                evidence["completed_cycles"] = cycle_number
                _write_evidence(output, evidence)
                print(
                    f"PASS cycle {cycle_number}/{args.cycles}; unplug again.", flush=True
                )
                cycle_number += 1
                state = "present"
            time.sleep(args.poll_ms / 1000.0)

        if cycle_number <= args.cycles:
            raise RuntimeError("overall timeout expired before all cycles completed")
        evidence["status"] = "PASS"
        evidence["evidence_boundary"]["verdict"] = "PASS"
        evidence["completed_at"] = _now()
        _write_evidence(output, evidence)
        print(f"PASS T-USB-007 evidence={output}")
        return 0
    except (OSError, RuntimeError) as exc:
        evidence["status"] = "FAIL"
        evidence["evidence_boundary"]["verdict"] = "NOT_QUALIFIED"
        evidence["completed_at"] = _now()
        evidence["failure"] = str(exc)
        _write_evidence(output, evidence)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--sysfs-root", type=Path, default=Path("/sys/bus/usb/devices"))
    parser.add_argument("--devfs-root", type=Path, default=Path("/dev/bus/usb"))
    parser.add_argument("--vid", default="34b7")
    parser.add_argument("--pid", default="1236")
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--minimum-disconnect-ms", type=int, default=250)
    parser.add_argument("--overall-timeout-seconds", type=int, default=3600)
    parser.add_argument("--recovery-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--smoke-retry-ms", type=int, default=100)
    parser.add_argument("--smoke-bytes", type=int, default=1_048_576)
    parser.add_argument(
        "--smoke-executable",
        type=Path,
        default=Path("host/target/release/hpm-usb-smoke"),
    )
    parser.add_argument("--firmware-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evidence/phase3/T-USB-007-current.json"),
    )
    parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    args = parser.parse_args()
    for name in (
        "cycles",
        "poll_ms",
        "minimum_disconnect_ms",
        "overall_timeout_seconds",
        "recovery_timeout_seconds",
        "smoke_retry_ms",
        "smoke_bytes",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
