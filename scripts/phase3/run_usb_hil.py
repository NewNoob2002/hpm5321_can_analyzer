#!/usr/bin/env python3
"""Run USB matrix and sustained loopback HIL against the P3A firmware."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import platform
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase0.usb_bulk_loopback import (  # noqa: E402
    DEVICE_OUT_WINDOW,
    EP_IN,
    EP_OUT,
    INTERFACE,
    LIBUSB_SUCCESS,
    PID,
    VID,
    error_name,
    load_libusb,
    terminate_hs_out_transfer,
    transfer,
)
from scripts.phase3.firmware_provenance import (  # noqa: E402
    verified_firmware_manifest,
)


DEFAULT_MANIFEST = ROOT / "build/hpm5321-flash-release/build-manifest.json"
DEFAULT_MATRIX_OUTPUT = ROOT / "docs/evidence/phase3/T-USB-005-008-010-current.json"
DEFAULT_LOOPBACK_OUTPUT = ROOT / "docs/evidence/phase3/T-USB-006-current.json"
FRAGMENT_SIZES = (1, 2, 7, 63, 64, 65, 127, 255, 511, 512, 513, 1023, 1024, 1535, 1536, 2047, 2048)
BACKPRESSURE_DELAYS_MS = (100, 1000, 5000, 15000)
RESET_PENDING_SIZES = (1, 512, 513, 2048)


def matrix_evidence_boundaries(
    verdict: str = "PARTIAL",
) -> dict[str, dict[str, Any]]:
    return {
        "T-USB-005": {
            "verdict": verdict,
            "covered": "raw vendor-bulk transfer sizes across USB packet and owner-buffer boundaries",
            "not_covered": "protocol-frame fragmentation and coalescing across USB transfers",
        },
        "T-USB-008": {
            "verdict": verdict,
            "covered": "single-buffer host-read pauses of 100, 1000, 5000, and 15000 ms with recovery probes",
            "not_covered": "sustained protocol workload, queue/drop reconciliation, and overload signaling",
        },
        "T-USB-010": {
            "verdict": verdict,
            "covered": "USB device reset and reopen with idle and pending raw echo data",
            "not_covered": "a real endpoint HALT/STALL condition and firmware recovery from CLEAR_FEATURE(ENDPOINT_HALT)",
        },
    }


def loopback_evidence_boundary(verdict: str = "PASS") -> dict[str, str]:
    return {
        "verdict": verdict,
        "covered": "at least 10 GiB and at least one hour of seeded raw vendor-bulk echo with byte-exact verification",
        "not_covered": "protocol/session, CAN data-plane, FS, Windows, hotplug, or endpoint HALT behavior",
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_ascii(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def device_metadata(sysfs_root: Path) -> dict[str, Any]:
    devices = []
    for candidate in sysfs_root.iterdir():
        if (
            read_ascii(candidate / "idVendor").casefold() == f"{VID:04x}"
            and read_ascii(candidate / "idProduct").casefold() == f"{PID:04x}"
        ):
            devices.append(candidate)
    if len(devices) != 1:
        raise RuntimeError(f"expected one {VID:04x}:{PID:04x} device, found {len(devices)}")
    device = devices[0]
    return {
        "topology_path": device.name,
        "busnum": read_ascii(device / "busnum"),
        "devnum": read_ascii(device / "devnum"),
        "speed_mbps": read_ascii(device / "speed"),
        "manufacturer": read_ascii(device / "manufacturer"),
        "product": read_ascii(device / "product"),
        "serial": read_ascii(device / "serial"),
    }


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def run_metadata(manifest_path: Path, sysfs_root: Path) -> dict[str, Any]:
    return {
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "repository": {
            "head": git_value("rev-parse", "HEAD"),
            "dirty": bool(git_value("status", "--short")),
        },
        "firmware_manifest": verified_firmware_manifest(manifest_path, ROOT),
        "device": device_metadata(sysfs_root),
    }


class UsbSession:
    def __init__(self, timeout_ms: int, recovery_timeout_seconds: float) -> None:
        self.timeout_ms = timeout_ms
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.lib = load_libusb()
        self.lib.libusb_reset_device.argtypes = [ctypes.c_void_p]
        self.lib.libusb_reset_device.restype = ctypes.c_int
        self.lib.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
        self.lib.libusb_clear_halt.restype = ctypes.c_int
        self.context = ctypes.c_void_p()
        self.handle: ctypes.c_void_p | None = None

    def __enter__(self) -> UsbSession:
        result = self.lib.libusb_init(ctypes.byref(self.context))
        if result != LIBUSB_SUCCESS:
            raise RuntimeError(f"libusb_init: {error_name(self.lib, result)}")
        self._open_with_retry()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._close_handle(release=True)
        self.lib.libusb_exit(self.context)

    def _open_with_retry(self) -> None:
        deadline = time.monotonic() + self.recovery_timeout_seconds
        last_error = "device absent"
        while time.monotonic() < deadline:
            handle = self.lib.libusb_open_device_with_vid_pid(self.context, VID, PID)
            if handle:
                result = self.lib.libusb_claim_interface(handle, INTERFACE)
                if result == LIBUSB_SUCCESS:
                    self.handle = handle
                    return
                last_error = f"claim interface: {error_name(self.lib, result)}"
                self.lib.libusb_close(handle)
            time.sleep(0.1)
        raise RuntimeError(f"USB recovery timed out: {last_error}")

    def _close_handle(self, release: bool) -> None:
        if not self.handle:
            return
        if release:
            self.lib.libusb_release_interface(self.handle, INTERFACE)
        self.lib.libusb_close(self.handle)
        self.handle = None

    def write(self, payload: bytes) -> None:
        if not self.handle:
            raise RuntimeError("USB handle is closed")
        transfer(self.lib, self.handle, EP_OUT, payload, self.timeout_ms)
        terminate_hs_out_transfer(
            self.lib, self.handle, len(payload), DEVICE_OUT_WINDOW, self.timeout_ms
        )

    def read(self, size: int) -> bytes:
        if not self.handle:
            raise RuntimeError("USB handle is closed")
        return transfer(self.lib, self.handle, EP_IN, bytes(size), self.timeout_ms)

    def echo(self, payload: bytes) -> None:
        self.write(payload)
        echoed = self.read(len(payload))
        if echoed != payload:
            mismatch = next(
                index
                for index, (expected, actual) in enumerate(zip(payload, echoed))
                if expected != actual
            )
            raise RuntimeError(f"content mismatch at payload offset {mismatch}")

    def reset_and_reopen(self) -> dict[str, Any]:
        if not self.handle:
            raise RuntimeError("USB handle is closed")
        started = time.monotonic()
        result = self.lib.libusb_reset_device(self.handle)
        result_name = error_name(self.lib, result)
        self._close_handle(release=False)
        if result != LIBUSB_SUCCESS:
            raise RuntimeError(f"libusb_reset_device: {result_name}")
        self._open_with_retry()
        for endpoint in (EP_OUT, EP_IN):
            clear_result = self.lib.libusb_clear_halt(self.handle, endpoint)
            if clear_result != LIBUSB_SUCCESS:
                raise RuntimeError(
                    f"clear halt 0x{endpoint:02x}: {error_name(self.lib, clear_result)}"
                )
        return {
            "libusb_result": result,
            "libusb_result_name": result_name,
            "reopen_ms": round((time.monotonic() - started) * 1000.0, 3),
        }


@dataclass(frozen=True)
class MatrixCase:
    name: str
    category: str
    action: Callable[[Any], dict[str, Any]]


def payload_bytes(rng: random.Random, size: int) -> bytes:
    return rng.randbytes(size)


def build_matrix_cases(
    rng: random.Random, sleep: Callable[[float], None] = time.sleep
) -> list[MatrixCase]:
    cases: list[MatrixCase] = []

    for size in FRAGMENT_SIZES:
        def fragmented(session: Any, size: int = size) -> dict[str, Any]:
            for _ in range(4):
                session.echo(payload_bytes(rng, size))
            return {"payload_size": size, "iterations": 4, "verified_bytes": size * 4}

        cases.append(MatrixCase(f"fragment-{size:04d}", "fragmentation", fragmented))

    for delay_ms in BACKPRESSURE_DELAYS_MS:
        def backpressure(session: Any, delay_ms: int = delay_ms) -> dict[str, Any]:
            payload = payload_bytes(rng, DEVICE_OUT_WINDOW)
            session.write(payload)
            sleep(delay_ms / 1000.0)
            echoed = session.read(len(payload))
            if echoed != payload:
                raise RuntimeError("content mismatch after host read pause")
            session.echo(payload_bytes(rng, 513))
            return {
                "host_read_pause_ms": delay_ms,
                "verified_bytes": len(payload) + 513,
                "post_resume_probe_bytes": 513,
            }

        cases.append(MatrixCase(f"backpressure-{delay_ms:05d}ms", "backpressure", backpressure))

    for cycle in range(1, 11):
        def idle_reset(session: Any, cycle: int = cycle) -> dict[str, Any]:
            reset = session.reset_and_reopen()
            session.echo(payload_bytes(rng, 2048))
            return {"reset_cycle": cycle, "post_reset_probe_bytes": 2048, **reset}

        cases.append(MatrixCase(f"reset-idle-{cycle:02d}", "reset", idle_reset))

    for size in RESET_PENDING_SIZES:
        def pending_reset(session: Any, size: int = size) -> dict[str, Any]:
            session.write(payload_bytes(rng, size))
            sleep(0.25)
            reset = session.reset_and_reopen()
            session.echo(payload_bytes(rng, 2048))
            return {
                "discarded_pending_echo_bytes": size,
                "post_reset_probe_bytes": 2048,
                **reset,
            }

        cases.append(MatrixCase(f"reset-pending-{size:04d}", "reset", pending_reset))

    return cases


def run_matrix(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "test_references": ["T-USB-005", "T-USB-008", "T-USB-010"],
        "evidence_boundaries": matrix_evidence_boundaries("PENDING"),
        "status_semantics": "PASS records completion of the raw preflight runner; referenced qualification verdicts are separate",
        "scope": "raw vendor-bulk boundary-size transfers, host-read pauses, and USB device reset recovery preflights",
        "status": "RUNNING",
        "started_at": now(),
        "seed": args.seed,
        "timeout_ms": args.timeout_ms,
        "recovery_timeout_seconds": args.recovery_timeout_seconds,
        "cases": [],
    }
    try:
        evidence.update(run_metadata(args.firmware_manifest.resolve(), args.sysfs_root))
        rng = random.Random(args.seed)
        cases = build_matrix_cases(rng)
        evidence["required_cases"] = len(cases)
        write_evidence(output, evidence)
        with UsbSession(args.timeout_ms, args.recovery_timeout_seconds) as session:
            for index, case in enumerate(cases, 1):
                started = time.monotonic()
                try:
                    details = case.action(session)
                except RuntimeError as exc:
                    evidence["cases"].append(
                        {
                            "index": index,
                            "name": case.name,
                            "category": case.category,
                            "status": "FAIL",
                            "elapsed_seconds": round(time.monotonic() - started, 6),
                            "failure": str(exc),
                        }
                    )
                    raise RuntimeError(f"{case.name}: {exc}") from exc
                evidence["cases"].append(
                    {
                        "index": index,
                        "name": case.name,
                        "category": case.category,
                        "status": "PASS",
                        "elapsed_seconds": round(time.monotonic() - started, 6),
                        **details,
                    }
                )
                evidence["completed_cases"] = index
                write_evidence(output, evidence)
                print(f"PASS matrix {index}/{len(cases)} {case.name}", flush=True)
        evidence["status"] = "PASS"
        evidence["evidence_boundaries"] = matrix_evidence_boundaries()
        evidence["completed_at"] = now()
        write_evidence(output, evidence)
        print(f"PASS USB matrix evidence={output}")
        return 0
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        evidence["status"] = "FAIL"
        evidence["evidence_boundaries"] = matrix_evidence_boundaries("NOT_QUALIFIED")
        evidence["completed_at"] = now()
        evidence["failure"] = str(exc)
        write_evidence(output, evidence)
        print(f"FAIL USB matrix: {exc}", file=sys.stderr)
        return 1


def minimums_met(total_bytes: int, elapsed_seconds: float, min_bytes: int, min_seconds: float) -> bool:
    return total_bytes >= min_bytes and elapsed_seconds >= min_seconds


def run_loopback(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "test_id": "T-USB-006",
        "evidence_boundary": loopback_evidence_boundary("PENDING"),
        "status_semantics": "PASS qualifies T-USB-006 only for the recorded raw pseudo-random echo workload",
        "status": "RUNNING",
        "started_at": now(),
        "seed": args.seed,
        "chunk_bytes": args.chunk,
        "required_bytes": args.min_bytes,
        "required_seconds": args.min_seconds,
        "timeout_ms": args.timeout_ms,
        "verified_bytes": 0,
        "verified_transfers": 0,
        "content_errors": 0,
        "progress": [],
    }
    try:
        if args.chunk <= 0 or args.chunk > DEVICE_OUT_WINDOW:
            raise RuntimeError(f"--chunk must be between 1 and {DEVICE_OUT_WINDOW}")
        evidence.update(run_metadata(args.firmware_manifest.resolve(), args.sysfs_root))
        write_evidence(output, evidence)
        rng = random.Random(args.seed)
        digest = hashlib.sha256()
        total_bytes = 0
        transfers = 0
        started = time.monotonic()
        next_report = started + args.report_seconds
        with UsbSession(args.timeout_ms, args.recovery_timeout_seconds) as session:
            while True:
                elapsed = time.monotonic() - started
                if minimums_met(total_bytes, elapsed, args.min_bytes, args.min_seconds):
                    break
                payload = payload_bytes(rng, args.chunk)
                try:
                    session.echo(payload)
                except RuntimeError:
                    evidence["content_errors"] += 1
                    raise
                digest.update(payload)
                total_bytes += len(payload)
                transfers += 1
                now_monotonic = time.monotonic()
                if now_monotonic >= next_report:
                    elapsed = now_monotonic - started
                    progress = {
                        "at": now(),
                        "verified_bytes": total_bytes,
                        "verified_transfers": transfers,
                        "elapsed_seconds": round(elapsed, 3),
                        "throughput_mib_s": round(total_bytes / 1_048_576.0 / elapsed, 3),
                    }
                    evidence["progress"].append(progress)
                    evidence.update(progress)
                    write_evidence(output, evidence)
                    print(
                        f"RUNNING bytes={total_bytes} elapsed_s={elapsed:.1f} "
                        f"throughput_MiB_s={progress['throughput_mib_s']:.3f}",
                        flush=True,
                    )
                    next_report = now_monotonic + args.report_seconds
        elapsed = time.monotonic() - started
        evidence.update(
            {
                "status": "PASS",
                "evidence_boundary": loopback_evidence_boundary(),
                "completed_at": now(),
                "verified_bytes": total_bytes,
                "verified_transfers": transfers,
                "elapsed_seconds": round(elapsed, 3),
                "throughput_mib_s": round(total_bytes / 1_048_576.0 / elapsed, 3),
                "payload_sha256": digest.hexdigest(),
                "byte_threshold_met": total_bytes >= args.min_bytes,
                "duration_threshold_met": elapsed >= args.min_seconds,
            }
        )
        write_evidence(output, evidence)
        print(
            f"PASS T-USB-006 bytes={total_bytes} elapsed_s={elapsed:.3f} "
            f"throughput_MiB_s={evidence['throughput_mib_s']:.3f} evidence={output}"
        )
        return 0
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        evidence["status"] = "FAIL"
        evidence["evidence_boundary"] = loopback_evidence_boundary("NOT_QUALIFIED")
        evidence["completed_at"] = now()
        evidence["failure"] = str(exc)
        write_evidence(output, evidence)
        print(f"FAIL T-USB-006: {exc}", file=sys.stderr)
        return 1


def common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout-ms", type=int, default=3000)
    parser.add_argument("--recovery-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0x5321)
    parser.add_argument("--sysfs-root", type=Path, default=Path("/sys/bus/usb/devices"))
    parser.add_argument("--firmware-manifest", type=Path, default=DEFAULT_MANIFEST)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    matrix = subparsers.add_parser("matrix")
    common_arguments(matrix)
    matrix.add_argument("--output", type=Path, default=DEFAULT_MATRIX_OUTPUT)
    matrix.set_defaults(run=run_matrix)

    loopback = subparsers.add_parser("loopback")
    common_arguments(loopback)
    loopback.add_argument("--output", type=Path, default=DEFAULT_LOOPBACK_OUTPUT)
    loopback.add_argument("--chunk", type=int, default=DEVICE_OUT_WINDOW)
    loopback.add_argument("--min-bytes", type=int, default=10 * 1024**3)
    loopback.add_argument("--min-seconds", type=float, default=3600.0)
    loopback.add_argument("--report-seconds", type=float, default=60.0)
    loopback.set_defaults(run=run_loopback)

    args = parser.parse_args()
    for name in ("timeout_ms", "recovery_timeout_seconds"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.command == "loopback":
        for name in ("min_bytes", "min_seconds", "report_seconds"):
            if getattr(args, name) <= 0:
                parser.error(f"--{name.replace('_', '-')} must be positive")
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
