#!/usr/bin/env python3
"""Validate the immutable non-PASS P3B bus-off attempt evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = Path(
    "docs/evidence/phase3/P3B-bus-off-attempt-2026-08-15.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_RAW_HASHES = {
    "build-manifest.json": "dbaeb3c2efda0097cc09ceecbfd91b8aa2430d2a21a2c2e82b91bfa87692f9cb",
    "build.txt": "b2aeb0cb6cccdd2d9155564a17d8646c2f913db0bc04c03bbfb8a6685067cbfe",
    "sha256.txt": "5e85eef11d285932a776784281546aea7a0e28cd5a08e076e52ab381db1d6ab5",
    "elf-readelf.txt": "dfaa79084f9266090288ee64252ffc11a9096747b85c9fdf40d224381e3e924d",
    "load-ram.gdb": "4fe0552d7732c9417b1425ceb5ae65a081d765cfbc00e3f8136286afbf106056",
    "load-ram-gdb.txt": "960f990ff087fe361eb64f9895a2216e0fc73ae4f0bf9630f82e234156ed7480",
    "preflight-snapshot-gdb.txt": "a8a7c2d59b4641e002069626bc89411bc9f9aa9d5400132121f5391d3c6c9d08",
    "run-nonce.txt": "a5bd8a4cea634ac6d5a69374a141b19b143212e4c67927eb17119ae29bd904ff",
    "arm-and-run.gdb": "ed84f0eb1dd4260f6a6657475e22976f0efe12af9866eb9480688a64230d9127",
    "arm-and-run-gdb.txt": "da466b27eb19f86f65bf22cd29fbe21077e2bb76f07f3b0c1ed0d0b747ee1785",
    "bounded-window.txt": "c71f29ad5ea42b3ca9edee24aa74e21b2d93e0b72b84a3d0f7956a90c4998534",
    "terminal-snapshot.gdb": "aac7168d29658c6d5be9294423603d35818deaf906eac11a418e5c79b6690cdc",
    "terminal-snapshot-gdb.txt": "a68f13dfb78e6199a4c29db403b895a1615540600537b5d918510943baf2c4d1",
    "timeout-dump.gdb": "468822fed462a4e2d53feae7f31f059ce101d81e8b87198a26cf02e321f99b44",
    "timeout-dump-gdb.txt": "ffbbb5de16da67bdf235456cb5472afe5ca0cb7dda7e6d23193109ae860c9326",
    "gdb-error-compat-test.txt": "fdd8dc646c971a1aa5e778e6fa5c7541ec2156b77ff0f6ca98918329809b04ae",
    "jlink-gdb-server.log": "1d19f7fb39721b2c921e7f31b33554dd89234617eff0a7a5cf0c9e3871960b92",
    "jlink-preflight-server.log": "488babc3be047ba145fb6532fa4b178febb885e7192518f4fd919c56b36c80fe",
    "jlink-arm-server.log": "e1e29bca4b7f92b78e6d8425260c6ce1237477676c5fed525f14477659c247a0",
    "jlink-terminal-server.log": "df3b9183161fd07d8dd52ddc8d12a9b5283c7727596565c10899b210bf5f2426",
    "jlink-timeout-dump-server.log": "4c6b7d42051492ccc4e5bb33e76b4b8ff76c7cbb3c57cf80442d7304db1d9414",
}
EXPECTED_MEMBERS = ["attempt-record.json", *EXPECTED_RAW_HASHES]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def read_json(data: bytes, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def validate_record(record: dict[str, Any], errors: list[str]) -> None:
    expected_top = {
        "schema": 1,
        "evidence_id": "P3B-bus-off-attempt-2026-08-15",
        "phase": "P3B",
        "test": "bus-off/manual fault injection",
    }
    for name, expected in expected_top.items():
        if record.get(name) != expected:
            errors.append(f"bus-off attempt mismatch: {name}")
    if record.get("execution") != {
        "executed": True,
        "outcome": "TIMEOUT_CLEANED_NOT_BUS_OFF",
        "status": "INCOMPLETE_PHYSICAL_FAULT_STIMULUS",
    }:
        errors.append("bus-off attempt execution outcome mismatch")
    hardware = record.get("hardware")
    if not isinstance(hardware, dict) or hardware != {
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
    }:
        errors.append("bus-off attempt hardware configuration mismatch")
    if record.get("stimulus") != {
        "frame_id": "0x7DE",
        "dlc": 8,
        "payload_prefix_hex": "424F4649",
        "run_nonce_hex": "0x6A80412F",
        "run_nonce_decimal": 1786790191,
        "tx_requests_submitted": 1,
        "active_timeout_ms": 2000,
    }:
        errors.append("bus-off attempt stimulus mismatch")
    if record.get("observed") != {
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
    }:
        errors.append("bus-off attempt observations mismatch")
    if record.get("containment") != {
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
    }:
        errors.append("bus-off attempt containment mismatch")
    if record.get("gates") != {
        "qualification_status": "PARTIAL",
        "p4e_gate": "BLOCKED",
        "pending": "bus-off/manual fault injection with active error injection",
    }:
        errors.append("bus-off attempt gates mismatch")
    interpretation = record.get("interpretation")
    if (
        not isinstance(interpretation, dict)
        or "not a bus-off HIL PASS" not in interpretation.get("forbidden_claim", "")
        or "bit/form/stuff-error" not in interpretation.get(
            "required_next_condition", ""
        )
    ):
        errors.append("bus-off attempt interpretation mismatch")


def validate(
    root: Path, evidence_relative: Path = DEFAULT_EVIDENCE
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    evidence_path = repository_file(
        root, evidence_relative.as_posix(), "bus-off attempt evidence", errors
    )
    if evidence_path is None:
        return errors
    evidence = read_json(
        evidence_path.read_bytes(), "bus-off attempt evidence", errors
    )
    validate_record(evidence, errors)

    raw_members = evidence.get("raw_members")
    expected_raw_members = [
        {
            "path": name,
            "sha256": digest,
            "size": None,
        }
        for name, digest in EXPECTED_RAW_HASHES.items()
    ]
    if not isinstance(raw_members, list):
        errors.append("bus-off attempt raw member references are missing")
        raw_members = []
    observed_raw_hashes = {
        item.get("path"): item.get("sha256")
        for item in raw_members
        if isinstance(item, dict)
    }
    if observed_raw_hashes != EXPECTED_RAW_HASHES:
        errors.append("bus-off attempt immutable raw hash set mismatch")
    if len(raw_members) != len(expected_raw_members) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("size"), int)
        or item["size"] <= 0
        for item in raw_members
    ):
        errors.append("bus-off attempt raw member metadata mismatch")

    package = evidence.get("package")
    if not isinstance(package, dict):
        errors.append("bus-off attempt package reference is missing")
        return errors
    package_path = repository_file(
        root, package.get("path"), "bus-off attempt package", errors
    )
    if package_path is None:
        return errors
    if package.get("members") != EXPECTED_MEMBERS:
        errors.append("bus-off attempt package member reference mismatch")
    if package.get("size") != package_path.stat().st_size:
        errors.append("bus-off attempt package size mismatch")
    if package.get("sha256") != sha256_file(package_path):
        errors.append("bus-off attempt package SHA-256 mismatch")

    archived: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append("bus-off attempt package comment is not allowed")
            if archive.namelist() != EXPECTED_MEMBERS:
                errors.append("bus-off attempt package member list mismatch")
            for info in archive.infolist():
                if info.date_time != FIXED_ZIP_TIME:
                    errors.append(f"bus-off attempt member timestamp mismatch: {info.filename}")
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    errors.append(f"bus-off attempt member compression mismatch: {info.filename}")
                if stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG:
                    errors.append(f"bus-off attempt member type mismatch: {info.filename}")
                archived[info.filename] = archive.read(info.filename)
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid bus-off attempt package: {exc}")
        return errors

    archived_record = read_json(
        archived.get("attempt-record.json", b""),
        "archived bus-off attempt record",
        errors,
    )
    evidence_record = dict(evidence)
    evidence_record.pop("package", None)
    if archived_record != evidence_record:
        errors.append("archived bus-off attempt record mismatch")
    for item in raw_members:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        name = item["path"]
        data = archived.get(name)
        if data is None:
            continue
        if item.get("size") != len(data) or item.get("sha256") != sha256_bytes(data):
            errors.append(f"bus-off attempt member reference mismatch: {name}")

    timeout_text = archived.get("timeout-dump-gdb.txt", b"").decode(
        "utf-8", errors="replace"
    )
    for fragment in (
        "state = 4",
        "run_nonce = 1786790191",
        "once_per_boot_consumed = 1",
        "tx_submit_count = 1",
        "max_tec = 128",
        "warning_observed = 1",
        "error_passive_observed = 1",
        "bus_off_observed = 0",
        "start_tick = 66200, end_tick = 68200",
        "final_tx_request_pending = 0",
        "cancel_timeout_observed = 0",
        "automatic_recovery_attempts = 0",
        "mode = 1, initialized = 1, online = 1, tx_armed = 0",
        "$4 = 0x60",
        "$5 = 0x0",
    ):
        if fragment not in timeout_text:
            errors.append(f"bus-off attempt timeout transcript mismatch: {fragment}")
    if archived.get("run-nonce.txt", b"").strip() != b"0x6A80412F":
        errors.append("bus-off attempt archived nonce mismatch")
    arm_text = archived.get("arm-and-run-gdb.txt", b"").decode(
        "utf-8", errors="replace"
    )
    if "P3B_BUS_OFF_ARMED nonce=0x6A80412F" not in arm_text:
        errors.append("bus-off attempt arm transcript mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    errors = validate(args.root, args.evidence)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS outcome=TIMEOUT_CLEANED_NOT_BUS_OFF; "
        "P3B PARTIAL; P4E BLOCKED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
