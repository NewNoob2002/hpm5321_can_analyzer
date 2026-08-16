#!/usr/bin/env python3
"""Package the 2026-08-15 P3B bus-off attempt as immutable non-PASS evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = Path("artifacts/p3b-bus-off-2026-08-15")
DEFAULT_EVIDENCE = Path(
    "docs/evidence/phase3/P3B-bus-off-attempt-2026-08-15.json"
)
DEFAULT_PACKAGE = Path(
    "docs/evidence/phase3/P3B-bus-off-attempt-2026-08-15.zip"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
RAW_MEMBERS = [
    "build-manifest.json",
    "build.txt",
    "sha256.txt",
    "elf-readelf.txt",
    "load-ram.gdb",
    "load-ram-gdb.txt",
    "preflight-snapshot-gdb.txt",
    "run-nonce.txt",
    "arm-and-run.gdb",
    "arm-and-run-gdb.txt",
    "bounded-window.txt",
    "terminal-snapshot.gdb",
    "terminal-snapshot-gdb.txt",
    "timeout-dump.gdb",
    "timeout-dump-gdb.txt",
    "gdb-error-compat-test.txt",
    "jlink-gdb-server.log",
    "jlink-preflight-server.log",
    "jlink-arm-server.log",
    "jlink-terminal-server.log",
    "jlink-timeout-dump-server.log",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def require_text(path: Path, fragments: tuple[str, ...]) -> None:
    text = path.read_text(errors="replace")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise ValueError(f"{path}: missing expected evidence fragments: {missing}")


def build_record(artifact_dir: Path) -> dict[str, object]:
    require_text(
        artifact_dir / "preflight-snapshot-gdb.txt",
        (
            "state = 1",
            "mode = 1, initialized = 1, online = 1, tx_armed = 0",
            "automatic_recovery_attempts = 0",
        ),
    )
    require_text(
        artifact_dir / "arm-and-run-gdb.txt",
        (
            "P3B_BUS_OFF_ARMED nonce=0x6A80412F",
            "command = 1",
        ),
    )
    require_text(
        artifact_dir / "timeout-dump-gdb.txt",
        (
            "state = 4",
            "run_nonce = 1786790191",
            "once_per_boot_consumed = 1",
            "tx_submit_count = 1",
            "last_submit_status = 0",
            "max_tec = 128",
            "warning_observed = 1",
            "error_passive_observed = 1",
            "bus_off_observed = 0",
            "start_tick = 66200, end_tick = 68200",
            "final_error_count = 1048704",
            "final_tx_request_pending = 0",
            "cancel_timeout_observed = 0",
            "automatic_recovery_attempts = 0",
            "mode = 1, initialized = 1, online = 1, tx_armed = 0",
            "$4 = 0x60",
            "$5 = 0x0",
        ),
    )
    require_text(
        artifact_dir / "gdb-error-compat-test.txt",
        ('ERROR: "compatibility-test"',),
    )
    require_text(
        artifact_dir / "jlink-arm-server.log",
        (
            "S/N: 607000454",
            "Target voltage: 3.32 V",
            'Device "HPM5321XCFX" selected.',
        ),
    )
    if (artifact_dir / "run-nonce.txt").read_text().strip() != "0x6A80412F":
        raise ValueError("run nonce evidence mismatch")

    raw_members = []
    for name in RAW_MEMBERS:
        path = artifact_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        raw_members.append(
            {
                "path": name,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )

    return {
        "schema": 1,
        "evidence_id": "P3B-bus-off-attempt-2026-08-15",
        "phase": "P3B",
        "test": "bus-off/manual fault injection",
        "execution": {
            "executed": True,
            "outcome": "TIMEOUT_CLEANED_NOT_BUS_OFF",
            "status": "INCOMPLETE_PHYSICAL_FAULT_STIMULUS",
        },
        "hardware": {
            "isolated_bench": True,
            "can_topology": ["DUT", "one CAN analyzer"],
            "analyzer_mode": "silent_listen_only",
            "active_fault_injector_present": False,
            "can_bitrate_bits_per_second": 1_000_000,
            "debugger": "J-Link PLUS",
            "debugger_serial": "607000454",
            "debug_interface": "JTAG",
            "debug_speed_khz": 4000,
            "target": "HPM5321xCFx",
            "target_voltage_v": 3.32,
        },
        "firmware": {
            "preset": "hpm5321-ram-debug-bus-off",
            "load_target": "RAM_ONLY",
            "elf_sha256": (
                "665869d1ddbcc312a884e8ab3ecb726774441d2c209f002b843017227cb8a05b"
            ),
            "source_revision": "afbf243e1b0e433deb9fad946dab7d4beb3b026a",
            "source_dirty": True,
        },
        "stimulus": {
            "frame_id": "0x7DE",
            "dlc": 8,
            "payload_prefix_hex": "424F4649",
            "run_nonce_hex": "0x6A80412F",
            "run_nonce_decimal": 1786790191,
            "tx_requests_submitted": 1,
            "active_timeout_ms": 2000,
        },
        "observed": {
            "result_state": "TIMEOUT_CLEANED",
            "result_state_value": 4,
            "last_submit_status": 0,
            "max_tec": 128,
            "warning_observed": 1,
            "error_passive_observed": 1,
            "bus_off_observed": 0,
            "final_psr_bo": 0,
            "start_tick": 66200,
            "end_tick": 68200,
            "elapsed_ticks": 2000,
            "final_protocol_status": 1891,
            "final_error_count": 1048704,
            "final_tx_request_pending": 0,
        },
        "containment": {
            "once_per_boot_consumed": 1,
            "cancel_timeout_observed": 0,
            "automatic_recovery_attempts": 0,
            "owner_mode": "LISTEN_ONLY",
            "owner_initialized": 1,
            "owner_online": 1,
            "owner_tx_armed": 0,
            "live_cccr": "0x60",
            "live_cccr_mon": 1,
            "live_txbrp": 0,
        },
        "tooling_finding": {
            "gdb_version": "13.2",
            "finding": "built-in error command unavailable",
            "mitigation_verified": "define error; echo ERROR; quit 1",
        },
        "interpretation": {
            "statement": (
                "The silent analyzer supplied no ACK. The DUT reached error-passive "
                "with TEC 128, did not reach bus-off, and was safely restored to "
                "listen-only after the 2000 ms bounded window."
            ),
            "required_next_condition": (
                "Provide a controlled active bit/form/stuff-error source that can "
                "continue driving transmit errors after the DUT becomes error-passive."
            ),
            "forbidden_claim": "This attempt is not a bus-off HIL PASS.",
        },
        "gates": {
            "qualification_status": "PARTIAL",
            "p4e_gate": "BLOCKED",
            "pending": "bus-off/manual fault injection with active error injection",
        },
        "raw_members": raw_members,
    }


def package(
    root: Path,
    artifact_dir_relative: Path,
    evidence_relative: Path,
    package_relative: Path,
) -> None:
    artifact_dir = root / artifact_dir_relative
    evidence_path = root / evidence_relative
    package_path = root / package_relative
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.parent.mkdir(parents=True, exist_ok=True)

    record = build_record(artifact_dir)
    record_data = json_bytes(record)
    members = ["attempt-record.json", *RAW_MEMBERS]
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr(zip_info("attempt-record.json"), record_data)
        for name in RAW_MEMBERS:
            archive.writestr(zip_info(name), (artifact_dir / name).read_bytes())

    evidence = {
        **record,
        "package": {
            "path": package_relative.as_posix(),
            "sha256": sha256_file(package_path),
            "size": package_path.stat().st_size,
            "members": members,
        },
    }
    evidence_path.write_bytes(json_bytes(evidence))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    args = parser.parse_args()
    package(args.root.resolve(), args.artifact_dir, args.evidence, args.package)
    print(f"WROTE {args.evidence}")
    print(f"WROTE {args.package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
