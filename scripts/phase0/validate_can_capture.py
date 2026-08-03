#!/usr/bin/env python3
"""Validate the bounded MCAN0 Phase 0 external-adapter capture."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

LINE_RE = re.compile(
    r"(\S+ \S+) Recv\[([0-9A-Fa-f]+)\]: ((?:[0-9A-Fa-f]{2} ?){8})"
)
ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MANIFEST_MEMBERS = (
    "boards/hpm5321_custom/CMakeLists.txt",
    "boards/hpm5321_custom/README.md",
    "boards/hpm5321_custom/board.c",
    "boards/hpm5321_custom/board.h",
    "boards/hpm5321_custom/clock.c",
    "boards/hpm5321_custom/clock.h",
    "boards/hpm5321_custom/hpm5321_custom.yaml",
    "boards/hpm5321_custom/pinmux.c",
    "boards/hpm5321_custom/pinmux.h",
    "tools/phase0/mcan0_external_probe/CMakeLists.txt",
    "tools/phase0/mcan0_external_probe/README.md",
    "tools/phase0/mcan0_external_probe/src/main.c",
    "scripts/phase0/generate_mcan0_source_manifest.sh",
    "scripts/phase0/rebuild_current_artifact.sh",
    "dependencies/hpm-sdk.lock",
    "CMakePresets.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_evidence_text(metadata: dict, path_key: str, hash_key: str) -> str:
    path = ROOT / metadata.get(path_key, "")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(f"invalid evidence path: {path_key}") from error
    if path.is_symlink() or not resolved.is_file():
        raise SystemExit(f"evidence must be a regular repository file: {path_key}")
    if metadata.get(hash_key) != sha256_file(resolved):
        raise SystemExit(f"evidence hash mismatch: {hash_key}")
    return resolved.read_text()


def verify_source_manifest(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"source manifest does not exist: {path}")
    seen = []
    resolved_seen = set()
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            expected, member_name = line.split("  ", 1)
        except ValueError as error:
            raise SystemExit(f"manifest line {line_number}: invalid syntax") from error
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise SystemExit(f"manifest line {line_number}: invalid SHA-256")
        member = Path(member_name)
        if member.is_absolute() or ".." in member.parts:
            raise SystemExit(f"manifest line {line_number}: unsafe member path")
        if member_name in seen:
            raise SystemExit(f"manifest line {line_number}: duplicate member")
        seen.append(member_name)
        member_path = ROOT / member
        try:
            resolved_member = member_path.resolve(strict=True)
            resolved_member.relative_to(ROOT.resolve())
        except (FileNotFoundError, ValueError) as error:
            raise SystemExit(f"manifest member escapes or is missing: {member_name}") from error
        if member_path.is_symlink():
            raise SystemExit(f"manifest member must not be a symlink: {member_name}")
        if resolved_member in resolved_seen:
            raise SystemExit(f"manifest members resolve to the same file: {member_name}")
        resolved_seen.add(resolved_member)
        if not resolved_member.is_file() or sha256_file(resolved_member) != expected:
            raise SystemExit(f"manifest member mismatch: {member_name}")
    if tuple(seen) != EXPECTED_MANIFEST_MEMBERS:
        raise SystemExit("manifest is not the canonical complete ordered member list")
    return sha256_file(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text())
    expected_metadata = {
        "adapter": "CANDBG-01",
        "channel": "CAN0",
        "bitrate": 500000,
        "frame_format": "standard",
        "protocol": "classic-can",
        "frame_type": "data",
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise SystemExit(
                f"metadata {key}: expected {expected!r}, got {metadata.get(key)!r}"
            )
    capture_digest = sha256_file(args.capture)
    if metadata.get("capture_sha256") != capture_digest:
        raise SystemExit("metadata capture_sha256 does not match capture")

    provenance = metadata.get("provenance_status")
    if provenance == "artifact-attested":
        elf_path = Path(metadata.get("elf_path", ""))
        if not elf_path.is_absolute():
            elf_path = ROOT / elf_path
        if not elf_path.is_file():
            raise SystemExit(f"metadata ELF does not exist: {elf_path}")
        elf_digest = sha256_file(elf_path)
        if metadata.get("elf_sha256") != elf_digest:
            raise SystemExit("metadata elf_sha256 does not match ELF")
    manifest_digest = metadata.get("source_manifest_sha256")
    if provenance == "historical-unbound":
        if metadata.get("approved_test_ids") != ["T-CAN-003"]:
            raise SystemExit("historical capture may map only to T-CAN-003")
        if manifest_digest is not None:
            raise SystemExit("historical-unbound metadata must use null manifest digest")
        if metadata.get("source_manifest_path") is not None:
            raise SystemExit("historical-unbound metadata must not name a source manifest")
        run_nonce = None
    elif provenance == "independent-results-unbound":
        if metadata.get("approved_test_ids") != ["T-CAN-003"]:
            raise SystemExit("unbound capture may map only to T-CAN-003")
        if metadata.get("artifact_attestation_path") is not None:
            raise SystemExit("unbound capture must not name an artifact attestation")
        run_nonce = None
    elif provenance == "artifact-attested":
        if metadata.get("approved_test_ids") != ["T-CAN-003", "T-CAN-013-subcase"]:
            raise SystemExit("current capture test-ID mapping is invalid")
        attestation_path = ROOT / metadata.get("artifact_attestation_path", "")
        if not attestation_path.is_file():
            raise SystemExit("artifact attestation does not exist")
        attestation = json.loads(attestation_path.read_text())
        run_nonce = metadata.get("run_nonce")
        if not isinstance(run_nonce, int) or not 0 < run_nonce <= 0xFFFF:
            raise SystemExit("artifact-attested capture requires a 16-bit run_nonce")
        if attestation.get("result_abi_version") < 5:
            raise SystemExit("same-run binding requires result ABI version 5 or later")
        if attestation.get("run_nonce") != run_nonce:
            raise SystemExit("capture run_nonce does not match artifact attestation")
        if attestation.get("external_capture_status") != "target_and_external_pass":
            raise SystemExit("artifact attestation does not declare external PASS")
        target_log = verified_evidence_text(
            metadata, "target_gdb_evidence", "target_gdb_sha256"
        )
        nonce_hex = f"0x{run_nonce:04X}"
        required_target_markers = (
            f"set variable g_mcan0_tx_run_nonce = {nonce_hex}",
            "set variable g_mcan0_tx_arm_token = 0x41524D21",
            f"ABI5_TERMINAL run_nonce=0x{run_nonce:04x} token=0x00000000",
            "magic = 0x444f4e45",
            "version = 0x5",
            f"run_nonce = 0x{run_nonce:04x}",
            "tx_attempted = 0x64",
            "tx_succeeded = 0x64",
            "cleanup_completed = 0x1",
        )
        if any(marker not in target_log for marker in required_target_markers):
            raise SystemExit("target GDB evidence lacks nonce/ARM/DONE/cleanup binding")
        flash_log = verified_evidence_text(
            metadata, "target_flash_verify_evidence", "target_flash_verify_sha256"
        )
        expected_flash_marker = f"ABI5_FLASH_ELF_SHA256 {metadata['elf_sha256']}"
        if expected_flash_marker not in flash_log or "Section .text" not in flash_log:
            raise SystemExit("target flash evidence does not bind the ELF")
        if any("mismatch" in line.lower() for line in flash_log.splitlines()):
            raise SystemExit("target flash compare-sections reported a mismatch")
        if metadata.get("elf_path") != attestation.get("artifact"):
            raise SystemExit("capture ELF path does not match artifact attestation")
        if metadata.get("elf_sha256") != attestation.get("elf_sha256"):
            raise SystemExit("capture ELF digest does not match artifact attestation")
        validator = ROOT / "scripts/phase0/validate_current_artifact.py"
        result = subprocess.run(
            [sys.executable, str(validator), str(attestation_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise SystemExit(f"artifact attestation validation failed: {detail}")
    else:
        raise SystemExit("unsupported provenance_status")

    rows = []
    for line_number, line in enumerate(args.capture.read_text().splitlines(), 1):
        match = LINE_RE.fullmatch(line)
        if match is None:
            raise SystemExit(f"line {line_number}: invalid capture syntax")
        timestamp = datetime.strptime(match.group(1), "%y-%m-%d %H:%M:%S.%f")
        can_id = int(match.group(2), 16)
        payload = bytes.fromhex(match.group(3))
        rows.append((timestamp, can_id, payload))

    if len(rows) != 100:
        raise SystemExit(f"expected 100 frames, got {len(rows)}")
    for sequence, (_, can_id, payload) in enumerate(rows):
        if run_nonce is None:
            expected = b"HPM0" + sequence.to_bytes(4, "big")
        else:
            expected = b"HP" + run_nonce.to_bytes(2, "big") + sequence.to_bytes(4, "big")
        if can_id != 0x123 or payload != expected:
            raise SystemExit(f"sequence {sequence}: ID or payload mismatch")

    intervals = [
        (current[0] - previous[0]).total_seconds() * 1000
        for previous, current in zip(rows, rows[1:])
    ]
    duration = (rows[-1][0] - rows[0][0]).total_seconds() * 1000
    if any(interval <= 0 for interval in intervals):
        raise SystemExit("timestamps are not strictly increasing")
    if not 900 <= duration <= 1100:
        raise SystemExit(f"capture duration outside 900..1100 ms: {duration:.3f}")
    mean_interval = sum(intervals) / len(intervals)
    if not 8 <= mean_interval <= 12:
        raise SystemExit(f"mean interval outside 8..12 ms: {mean_interval:.3f}")
    if min(intervals) < 1 or max(intervals) > 20:
        raise SystemExit(
            f"individual interval outside 1..20 ms: {min(intervals):.3f}..{max(intervals):.3f}"
        )

    print(
        "PASS adapter=CANDBG-01 channel=CAN0 bitrate=500000 "
        "format=standard protocol=classic-can type=data "
        "count=100 id=0x123 dlc=8 sequence=0..99"
    )
    print(f"duration_ms={duration:.3f}")
    print(
        f"interval_ms min={min(intervals):.3f} "
        f"max={max(intervals):.3f} mean={mean_interval:.3f}"
    )


if __name__ == "__main__":
    main()
