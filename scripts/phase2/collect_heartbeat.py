#!/usr/bin/env python3
"""Collect reset, fault, heartbeat, stack, and voter evidence through J-Link."""

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


ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION_SECONDS = 24 * 60 * 60
SAMPLE_PATTERN = re.compile(
    r"P2_SAMPLE "
    r"boot=(?P<boot>[0-9a-fA-F]+) "
    r"boot_tick=(?P<boot_tick>\d+) "
    r"reset=(?P<reset>[0-9a-fA-F]+) "
    r"heartbeat=(?P<heartbeat>\d+) "
    r"drops=(?P<drops>\d+) "
    r"stack=(?P<stack>\d+) "
    r"tick=(?P<tick>\d+) "
    r"fault_magic=(?P<fault_magic>[0-9a-fA-F]+) "
    r"fault_reason=(?P<fault_reason>\d+) "
    r"evaluations=(?P<evaluations>\d+) "
    r"healthy=(?P<healthy>\d+) "
    r"missing=(?P<missing>[0-9a-fA-F]+) "
    r"stall=(?P<stall>[0-9a-fA-F]+) "
    r"alloc_frozen=(?P<alloc_frozen>\d+) "
    r"allocations=(?P<allocations>\d+) "
    r"post_freeze_allocations=(?P<post_freeze_allocations>\d+) "
    r"mcan_magic=(?P<mcan_magic>[0-9a-fA-F]+) "
    r"mcan_priority=(?P<mcan_priority>\d+) "
    r"mcan_irqs=(?P<mcan_irqs>\d+) "
    r"mcan_submitted=(?P<mcan_submitted>\d+) "
    r"mcan_received=(?P<mcan_received>\d+) "
    r"mcan_matched=(?P<mcan_matched>\d+) "
    r"mcan_queue_sends=(?P<mcan_queue_sends>\d+) "
    r"mcan_queue_drops=(?P<mcan_queue_drops>\d+) "
    r"mcan_errors=(?P<mcan_errors>[0-9a-fA-F]+) "
    r"mcan_terminal_faults=(?P<mcan_terminal_faults>[0-9a-fA-F]+) "
    r"mcan_tx_errors=(?P<mcan_tx_errors>\d+) "
    r"mcan_rx_errors=(?P<mcan_rx_errors>\d+) "
    r"mcan_error_log=(?P<mcan_error_log>\d+) "
    r"mcan_mismatches=(?P<mcan_mismatches>\d+) "
    r"mcan_timeouts=(?P<mcan_timeouts>\d+) "
    r"mcan_stack=(?P<mcan_stack>\d+) "
    r"mcan_cleanup_status=(?P<mcan_cleanup_status>-?\d+) "
    r"mcan_cccr=(?P<mcan_cccr>[0-9a-fA-F]+) "
    r"mcan_cleanup=(?P<mcan_cleanup>\d+)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _bounded_sleep_seconds(interval: float, remaining: float) -> float:
    return max(0.0, min(interval, remaining))


def parse_sample(output: str) -> dict[str, int]:
    match = SAMPLE_PATTERN.search(output)
    if match is None:
        raise RuntimeError("GDB output does not contain a P2_SAMPLE record")

    hexadecimal = {
        "boot",
        "reset",
        "fault_magic",
        "missing",
        "stall",
        "mcan_magic",
        "mcan_errors",
        "mcan_terminal_faults",
        "mcan_cccr",
    }
    return {
        name: int(value, 16 if name in hexadecimal else 10)
        for name, value in match.groupdict().items()
    }


def validate_sample(
    sample: dict[str, int], previous: dict[str, int] | None, minimum_stack: int
) -> None:
    if sample["boot"] != 0x424F4F54:
        raise RuntimeError("boot magic is invalid")
    if sample["fault_magic"] != 0 or sample["fault_reason"] != 0:
        raise RuntimeError("target recorded a fault")
    if sample["drops"] != 0:
        raise RuntimeError("health timer queue dropped an event")
    if sample["stack"] < minimum_stack:
        raise RuntimeError("health task stack watermark is below the threshold")
    if sample["missing"] != 0 or sample["stall"] != 0:
        raise RuntimeError("watchdog voter state is not healthy")
    if sample["healthy"] != sample["evaluations"]:
        raise RuntimeError("watchdog history contains a missing voter")
    if sample["alloc_frozen"] != 1:
        raise RuntimeError("runtime allocation policy is not frozen")
    if sample["post_freeze_allocations"] != 0:
        raise RuntimeError("runtime allocation occurred after the freeze point")
    if sample["mcan_magic"] != 0x50415353:
        raise RuntimeError("MCAN0 IRQ qualification did not complete")
    if sample["mcan_priority"] != 4:
        raise RuntimeError("MCAN0 ISR priority is not 4")
    expected_frames = 1024
    for field in (
        "mcan_irqs",
        "mcan_submitted",
        "mcan_received",
        "mcan_matched",
        "mcan_queue_sends",
    ):
        if sample[field] != expected_frames:
            raise RuntimeError(f"MCAN0 qualification count is invalid: {field}")
    if sample["mcan_queue_drops"] != 0:
        raise RuntimeError("MCAN0 ISR queue dropped a frame")
    if sample["mcan_errors"] != 0:
        raise RuntimeError("MCAN0 IRQ qualification recorded an error interrupt")
    if sample["mcan_terminal_faults"] != 0:
        raise RuntimeError("MCAN0 IRQ qualification ended with a fault flag")
    if (sample["mcan_tx_errors"] != 0 or sample["mcan_rx_errors"] != 0 or
            sample["mcan_error_log"] != 0):
        raise RuntimeError("MCAN0 IRQ qualification ended with error counters")
    if sample["mcan_mismatches"] != 0 or sample["mcan_timeouts"] != 0:
        raise RuntimeError("MCAN0 IRQ qualification recorded a frame failure")
    if sample["mcan_stack"] < minimum_stack:
        raise RuntimeError("MCAN0 receiver stack watermark is below the threshold")
    if (sample["mcan_cleanup_status"] != 0 or sample["mcan_cleanup"] != 1 or
            (sample["mcan_cccr"] & 1) == 0):
        raise RuntimeError("MCAN0 controller cleanup did not reach INIT state")
    if previous is not None:
        if sample["boot_tick"] != previous["boot_tick"]:
            raise RuntimeError("boot timestamp changed; target reset detected")
        if sample["reset"] != previous["reset"]:
            raise RuntimeError("reset-source snapshot changed")
        if sample["heartbeat"] <= previous["heartbeat"]:
            raise RuntimeError("heartbeat did not advance; reset or stall suspected")
        if sample["tick"] <= previous["tick"]:
            raise RuntimeError("MCHTMR timestamp did not advance")
        if sample["evaluations"] <= previous["evaluations"]:
            raise RuntimeError("watchdog evaluation generation did not advance")


def _sample_target(gdb: Path, elf: Path, port: int) -> dict[str, int]:
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
        (
            'printf "P2_SAMPLE boot=%08x boot_tick=%llu reset=%08x '
            "heartbeat=%u drops=%u "
            "stack=%u tick=%llu fault_magic=%08x fault_reason=%u "
            "evaluations=%u healthy=%u missing=%08x stall=%08x "
            "alloc_frozen=%u allocations=%u post_freeze_allocations=%u "
            "mcan_magic=%08x mcan_priority=%u mcan_irqs=%u "
            "mcan_submitted=%u mcan_received=%u mcan_matched=%u "
            "mcan_queue_sends=%u mcan_queue_drops=%u mcan_errors=%08x "
            "mcan_terminal_faults=%08x mcan_tx_errors=%u mcan_rx_errors=%u "
            "mcan_error_log=%u mcan_mismatches=%u mcan_timeouts=%u "
            "mcan_stack=%u mcan_cleanup_status=%d mcan_cccr=%08x "
            "mcan_cleanup=%u\\n\", "
            "g_app_boot_state.magic, g_app_boot_state.boot_timestamp, "
            "g_app_boot_state.reset_flags, "
            "g_app_health_state.heartbeat_count, "
            "g_app_health_state.timer_queue_drops, "
            "g_app_health_state.stack_high_watermark, "
            "g_app_health_state.last_heartbeat_tick, "
            "g_app_fault_state.magic, g_app_fault_state.reason, "
            "g_app_watchdog_state.evaluation_count, "
            "g_app_watchdog_state.healthy_evaluation_count, "
            "g_app_watchdog_state.missing_mask, "
            "g_app_watchdog_state.test_stall_mask, "
            "g_app_allocation_state.frozen, "
            "g_app_allocation_state.allocation_calls, "
            "g_app_allocation_state.post_freeze_allocation_calls, "
            "g_app_mcan_irq_test_state.magic, "
            "g_app_mcan_irq_test_state.irq_priority, "
            "g_app_mcan_irq_test_state.interrupt_count, "
            "g_app_mcan_irq_test_state.frames_submitted, "
            "g_app_mcan_irq_test_state.frames_received, "
            "g_app_mcan_irq_test_state.frames_matched, "
            "g_app_mcan_irq_test_state.queue_send_count, "
            "g_app_mcan_irq_test_state.queue_drops, "
            "g_app_mcan_irq_test_state.error_interrupt_flags, "
            "g_app_mcan_irq_test_state.terminal_fault_flags, "
            "g_app_mcan_irq_test_state.tx_error_count, "
            "g_app_mcan_irq_test_state.rx_error_count, "
            "g_app_mcan_irq_test_state.error_logging_count, "
            "g_app_mcan_irq_test_state.frame_mismatches, "
            "g_app_mcan_irq_test_state.receive_timeouts, "
            "g_app_mcan_irq_test_state.receiver_stack_high_watermark, "
            "g_app_mcan_irq_test_state.cleanup_status, "
            "g_app_mcan_irq_test_state.post_cleanup_cccr, "
            "g_app_mcan_irq_test_state.cleanup_completed"
        ),
        "-ex",
        "monitor go",
        "-ex",
        "detach",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"GDB sample failed: {output.strip()}")
    return parse_sample(output)


def collect(
    args: argparse.Namespace,
    sampler: Callable[[Path, Path, int], dict[str, int]] = _sample_target,
) -> int:
    elf = args.elf.resolve()
    output = args.output.resolve()
    evidence: dict[str, Any] = {
        "schema_version": 2,
        "test_id": args.test_id,
        "status": "RUNNING",
        "qualification_status": "PARTIAL",
        "started_at": _now(),
        "operator": args.operator,
        "requested_duration_seconds": args.duration_seconds,
        "qualification_duration_seconds": (
            QUALIFICATION_SECONDS if args.test_id == "T-RTOS-003" else 0
        ),
        "interval_seconds": args.interval_seconds,
        "minimum_stack_words": args.minimum_stack_words,
        "elf": str(elf.relative_to(ROOT) if elf.is_relative_to(ROOT) else elf),
        "elf_sha256": "",
        "samples": [],
    }
    server: subprocess.Popen[bytes] | None = None

    try:
        if not elf.is_file():
            raise RuntimeError(f"ELF does not exist: {elf}")
        evidence["elf_sha256"] = _sha256(elf)
        server_command = [
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
        ]
        server = subprocess.Popen(
            server_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(args.server_start_seconds)
        if server.poll() is not None:
            raise RuntimeError("J-Link GDB server exited before sampling")

        started = time.monotonic()
        previous: dict[str, int] | None = None
        while True:
            sample = sampler(args.gdb, elf, args.port)
            validate_sample(sample, previous, args.minimum_stack_words)
            sample["elapsed_seconds"] = round(time.monotonic() - started, 3)
            sample["collected_at"] = _now()
            evidence["samples"].append(sample)
            _write_evidence(output, evidence)
            print(
                f"sample={len(evidence['samples'])} "
                f"heartbeat={sample['heartbeat']} missing=0x{sample['missing']:x} "
                f"mcan={sample['mcan_matched']}/{sample['mcan_submitted']}",
                flush=True,
            )
            previous = sample
            elapsed = time.monotonic() - started
            if elapsed >= args.duration_seconds and len(evidence["samples"]) >= 2:
                break
            time.sleep(
                _bounded_sleep_seconds(
                    args.interval_seconds, args.duration_seconds - elapsed
                )
            )

        evidence["actual_duration_seconds"] = round(
            time.monotonic() - started, 3
        )
        evidence["completed_at"] = _now()
        evidence["status"] = "PASS"
        if (args.test_id == "T-RTOS-005" or
                evidence["actual_duration_seconds"] >= QUALIFICATION_SECONDS):
            evidence["qualification_status"] = "PASS"
        _write_evidence(output, evidence)
        print(
            f"PASS collector qualification={evidence['qualification_status']} "
            f"evidence={output}"
        )
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence["status"] = "FAIL"
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
    parser.add_argument(
        "--test-id",
        choices=("T-RTOS-003", "T-RTOS-005"),
        default="T-RTOS-003",
    )
    parser.add_argument(
        "--elf",
        type=Path,
        default=ROOT / "build/hpm5321-flash-debug/output/demo.elf",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/evidence/phase2/T-RTOS-003-current.json",
    )
    parser.add_argument("--duration-seconds", type=float, default=QUALIFICATION_SECONDS)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--minimum-stack-words", type=int, default=128)
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
        "duration_seconds",
        "interval_seconds",
        "minimum_stack_words",
        "server_start_seconds",
        "jtag_khz",
        "port",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
