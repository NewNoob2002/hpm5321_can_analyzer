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


def usb_device_node(device: Path) -> Path | None:
    try:
        bus = int(_read_text(device / "busnum"))
        number = int(_read_text(device / "devnum"))
    except ValueError:
        return None
    return Path("/dev/bus/usb") / f"{bus:03d}" / f"{number:03d}"


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

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "test_id": "T-USB-007",
        "status": "RUNNING",
        "started_at": _now(),
        "operator": args.operator,
        "disconnect_method": "physical-cable",
        "vid": args.vid.lower(),
        "pid": args.pid.lower(),
        "required_cycles": args.cycles,
        "completed_cycles": 0,
        "minimum_disconnect_ms": args.minimum_disconnect_ms,
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

        evidence["topology_path"] = devices[0].name
        device_node = usb_device_node(devices[0])
        if device_node is not None:
            evidence["device_node"] = str(device_node)
            evidence["device_node_readable"] = os.access(device_node, os.R_OK)
            evidence["device_node_writable"] = os.access(device_node, os.W_OK)
            if not (
                evidence["device_node_readable"]
                and evidence["device_node_writable"]
            ):
                raise RuntimeError(
                    f"USB device node is not readable/writable: {device_node}; "
                    "install config/udev/99-hpm5321-can-analyzer.rules and reconnect"
                )
        evidence["initial_smoke"] = _run_smoke(executable, args.smoke_bytes)
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
                smoke = _run_smoke(executable, args.smoke_bytes)
                cycle = {
                    "cycle": cycle_number,
                    "disconnected_at": disconnected_wall,
                    "reconnected_at": _now(),
                    "disconnect_ms": round(absent_ms, 3),
                    "topology_path": devices[0].name,
                    "recovery_smoke": smoke,
                }
                evidence["cycles"].append(cycle)
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
        evidence["completed_at"] = _now()
        _write_evidence(output, evidence)
        print(f"PASS T-USB-007 evidence={output}")
        return 0
    except (OSError, RuntimeError) as exc:
        evidence["status"] = "FAIL"
        evidence["completed_at"] = _now()
        evidence["failure"] = str(exc)
        _write_evidence(output, evidence)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--sysfs-root", type=Path, default=Path("/sys/bus/usb/devices"))
    parser.add_argument("--vid", default="34b7")
    parser.add_argument("--pid", default="1236")
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--minimum-disconnect-ms", type=int, default=250)
    parser.add_argument("--overall-timeout-seconds", type=int, default=3600)
    parser.add_argument("--smoke-bytes", type=int, default=1_048_576)
    parser.add_argument(
        "--smoke-executable",
        type=Path,
        default=Path("host/target/release/hpm-usb-smoke"),
    )
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
        "smoke_bytes",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
