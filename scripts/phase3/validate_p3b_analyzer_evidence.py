#!/usr/bin/env python3
"""Validate immutable low-rate independent analyzer reconciliation evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = Path(
    "docs/evidence/phase3/P3B-HIL-analyzer-low-rate-evidence-2026-08-15.json"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = [
    "run-manifest.json",
    "summary.json",
    "diagnostics.csv",
    "pings.csv",
    "data_loss.csv",
    "events.csv",
    "frames.csv",
    "analyzer-log.txt",
    "bit-timing.png",
    "analyzer-reconciliation.json",
    "capture/capture-tool-anchor.json",
    "capture/can_hil_capture.rs",
    "capture/can_hil_capture",
    "reconcile/reconcile_p3b_analyzer.py",
    "operator-attestation.txt",
]
RUN_FILES = PACKAGE_MEMBERS[1:10]
EXPECTED_SOURCE_HASHES = {
    "summary.json": "9677e9762eafbabdd12f3f772ca04bd158450e2117135b438d42dc3c29921b40",
    "diagnostics.csv": "c3ac6f0c5e14f931deb4a0619cf435ce25fffa6215e01f9c0a8394d6e0569087",
    "pings.csv": "5bdde98ca322913e536b66704e1acf20172bb3a2624ad65cd30479efc5609100",
    "data_loss.csv": "01af27eb48d98a511d7f535f9566a2aa0017cd19e3be53f85d7453558238fd41",
    "events.csv": "7dbdbcd80946cbab6dc0bfcb0bcb12e9a9052c97bff3bb58857fce9c5a9e7c9c",
    "frames.csv": "972ad238068a6270a5f2862c30bcadddc09b27aa271e8c1f21876c05d0efb9f7",
    "analyzer-log.txt": "9b1b9f6a16312332b6cd7229b6a897f0dde876e8c3dd8e5f71298ae68cf4dd7f",
    "bit-timing.png": "ba5aff904a141924727250fc469fb2a2c885595f18e9705a267e7cd98ee869e1",
    "analyzer-reconciliation.json": "ac496288e8939b7ddc641fae4531c7b1e8067dc0d28b838013dd0bacd16454b6",
}
EXPECTED_CAPTURE_ANCHOR_SHA256 = (
    "26d53f98e630eccaf1c9dfc42c3c49f36bc10a5e84c744ea7eb7b28679717108"
)
EXPECTED_STATEMENT = (
    "The export-capable approximately 64 frame/s analyzer window exactly "
    "matches all 11459 DUT frames by count, identifier, DLC, and payload. "
    "Because every frame is identical, independent order permutations are "
    "not distinguishable. Its active-span rate agrees with the DUT capture, and the "
    "archived analyzer configuration screenshot records a 1 Mbit/s "
    "arbitration bitrate."
)
EXPECTED_OUTCOMES = {
    "frame_count_and_content_reconciliation": "PASS",
    "record_order_reconciliation": "NOT_DISTINGUISHABLE_IDENTICAL_FRAMES",
    "coarse_timestamp_and_rate_reconciliation": "PASS_WITH_LIMITATION",
    "nominal_1_mbit_configuration_reconciliation": "PASS",
    "high_rate_analyzer_timestamp_coverage": "NOT_CLAIMED",
    "detailed_sample_point_and_waveform_reconciliation": "NOT_COVERED",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"invalid {label}")
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        errors.append(f"invalid {label}")
        return None
    if str(path) != value:
        errors.append(f"invalid {label}")
        return None
    return value


def repository_file(
    root: Path, relative: object, label: str, errors: list[str]
) -> Path | None:
    value = safe_relative_path(relative, label, errors)
    if value is None:
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


def json_object(data: bytes, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} root must be an object")
        return {}
    return value


def load_reconciler():
    path = ROOT / "scripts/phase3/reconcile_p3b_analyzer.py"
    spec = importlib.util.spec_from_file_location("p3b_analyzer_reconciler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_zip_info(
    info: zipfile.ZipInfo, expected: str, errors: list[str]
) -> None:
    safe_relative_path(info.filename, "analyzer package member", errors)
    if info.filename != expected:
        errors.append("analyzer package member list mismatch")
    if (
        info.date_time != FIXED_ZIP_TIME
        or info.create_system != 3
        or info.compress_type != zipfile.ZIP_STORED
        or info.flag_bits != 0
        or info.internal_attr != 0
        or info.external_attr != 0o100644 << 16
        or info.extra
        or info.comment
    ):
        errors.append(f"analyzer package member metadata mismatch: {info.filename}")
    if not 0 < info.file_size <= 64 * 1024 * 1024:
        errors.append(f"analyzer package member size is invalid: {info.filename}")


def validate(
    root: Path, evidence_relative: Path = DEFAULT_EVIDENCE
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    evidence_path = repository_file(
        root, evidence_relative.as_posix(), "analyzer evidence", errors
    )
    if evidence_path is None:
        return errors
    evidence = json_object(evidence_path.read_bytes(), "analyzer evidence", errors)
    if evidence.get("schema") != 1:
        errors.append("unsupported analyzer evidence schema")
    if (
        evidence.get("evidence_id")
        != "P3B-HIL-analyzer-low-rate-evidence-2026-08-15"
    ):
        errors.append("unexpected analyzer evidence ID")
    if evidence.get("phase") != "P3B":
        errors.append("analyzer evidence phase must be P3B")
    if evidence.get("status") != "PASS_WITH_LIMITATION":
        errors.append("analyzer evidence must remain PASS_WITH_LIMITATION")
    if evidence.get("outcomes") != EXPECTED_OUTCOMES:
        errors.append("analyzer evidence outcomes mismatch")

    package = evidence.get("package")
    if not isinstance(package, dict):
        errors.append("analyzer package reference is missing")
        return errors
    package_path = repository_file(
        root, package.get("path"), "analyzer package", errors
    )
    if package_path is None:
        return errors
    if package.get("size") != package_path.stat().st_size:
        errors.append("analyzer package size mismatch")
    if package.get("sha256") != sha256_file(package_path):
        errors.append("analyzer package SHA-256 mismatch")
    if package.get("members") != PACKAGE_MEMBERS:
        errors.append("analyzer package member reference mismatch")

    members: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(package_path) as archive:
            if archive.comment:
                errors.append("analyzer package comment is not allowed")
            if archive.namelist() != PACKAGE_MEMBERS:
                errors.append("analyzer package member list mismatch")
            for info, expected in zip(
                archive.infolist(), PACKAGE_MEMBERS, strict=False
            ):
                validate_zip_info(info, expected, errors)
            for name in PACKAGE_MEMBERS:
                members[name] = archive.read(name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid analyzer package: {exc}")
        return errors

    if package.get("run_manifest_sha256") != sha256_bytes(
        members["run-manifest.json"]
    ):
        errors.append("analyzer run manifest SHA-256 mismatch")
    for name, expected_hash in EXPECTED_SOURCE_HASHES.items():
        if sha256_bytes(members[name]) != expected_hash:
            errors.append(f"unexpected immutable analyzer source hash: {name}")

    manifest = json_object(
        members["run-manifest.json"], "analyzer run manifest", errors
    )
    summary = json_object(members["summary.json"], "analyzer summary", errors)
    recorded = json_object(
        members["analyzer-reconciliation.json"],
        "analyzer reconciliation",
        errors,
    )
    if manifest.get("schema") != 1:
        errors.append("unsupported analyzer run manifest schema")
    if manifest.get("evidence_id") != "P3B-HIL-analyzer-low-rate-2026-08-15":
        errors.append("unexpected analyzer run evidence ID")
    if manifest.get("phase") != "P3B":
        errors.append("analyzer run phase must be P3B")
    if manifest.get("result") != "PASS_WITH_LIMITATION":
        errors.append("analyzer run result must remain PASS_WITH_LIMITATION")
    command = manifest.get("command")
    if not isinstance(command, str) or "can_hil_capture -- 5 180" not in command:
        errors.append("analyzer run command mismatch")

    references = manifest.get("files")
    if not isinstance(references, dict):
        errors.append("analyzer run file references are missing")
        references = {}
    for name in RUN_FILES:
        if references.get(name) != {
            "sha256": sha256_bytes(members[name]),
            "size": len(members[name]),
        }:
            errors.append(f"analyzer member reference mismatch: {name}")

    capture = manifest.get("capture_tool")
    archived_anchor = members["capture/capture-tool-anchor.json"]
    anchor_path = repository_file(
        root,
        "docs/evidence/phase3/P3B-capture-tool-anchor-2026-08-15.json",
        "capture tool anchor",
        errors,
    )
    if sha256_bytes(archived_anchor) != EXPECTED_CAPTURE_ANCHOR_SHA256:
        errors.append("unexpected immutable capture tool anchor hash")
    if anchor_path is not None:
        if sha256_file(anchor_path) != EXPECTED_CAPTURE_ANCHOR_SHA256:
            errors.append("versioned capture tool anchor hash mismatch")
        if anchor_path.read_bytes() != archived_anchor:
            errors.append("versioned capture tool anchor differs from archived anchor")
    expected_capture = {
        "source_commit": "afbf243e1b0e433deb9fad946dab7d4beb3b026a",
        "source_dirty": True,
        "anchor_member": "capture/capture-tool-anchor.json",
        "anchor_sha256": EXPECTED_CAPTURE_ANCHOR_SHA256,
        "source_member": "capture/can_hil_capture.rs",
        "source_sha256": "6944d5150086a17605e37c10e4d220258eff964783ad7b9544b9c53181636541",
        "binary_member": "capture/can_hil_capture",
        "binary_sha256": "1791cb97ea8dd37abbae04cab7bb7a8a6cb0d98898bc81637d6de7549b3e8587",
        "binary_size": 727744,
        "compiler": "rustc 1.97.1 (8bab26f4f 2026-07-14)",
    }
    if capture != expected_capture:
        errors.append("analyzer capture tool evidence mismatch")
    capture_anchor = json_object(archived_anchor, "capture tool anchor", errors)
    if capture_anchor != {
        "schema": 1,
        "evidence_id": "P3B-capture-tool-anchor-2026-08-15",
        "phase": "P3B",
        "source": {
            "commit": expected_capture["source_commit"],
            "dirty": expected_capture["source_dirty"],
            "member": expected_capture["source_member"],
            "sha256": expected_capture["source_sha256"],
            "size": len(members["capture/can_hil_capture.rs"]),
        },
        "binary": {
            "member": expected_capture["binary_member"],
            "sha256": expected_capture["binary_sha256"],
            "size": expected_capture["binary_size"],
        },
        "compiler": expected_capture["compiler"],
    }:
        errors.append("analyzer capture tool anchor content mismatch")
    if sha256_bytes(members["capture/can_hil_capture.rs"]) != expected_capture[
        "source_sha256"
    ]:
        errors.append("analyzer capture source does not match immutable anchor")
    if sha256_bytes(members["capture/can_hil_capture"]) != expected_capture[
        "binary_sha256"
    ]:
        errors.append("analyzer capture binary does not match immutable anchor")

    archived_reconciler = members["reconcile/reconcile_p3b_analyzer.py"]
    current_reconciler = root / "scripts/phase3/reconcile_p3b_analyzer.py"
    if manifest.get("reconciliation_tool") != {
        "member": "reconcile/reconcile_p3b_analyzer.py",
        "sha256": sha256_bytes(archived_reconciler),
    }:
        errors.append("analyzer reconciliation tool evidence mismatch")
    if sha256_file(current_reconciler) != sha256_bytes(archived_reconciler):
        errors.append("versioned analyzer reconciler differs from archived tool")

    if manifest.get("operator_attestation") != {
        "member": "operator-attestation.txt",
        "sha256": sha256_bytes(members["operator-attestation.txt"]),
    }:
        errors.append("analyzer operator attestation evidence mismatch")
    if (
        sha256_bytes(members["operator-attestation.txt"])
        != "fa9e80b5c532bb5c898e58ebe6741d29a6fe58ff4c3d4546abca32ddd5674c9b"
    ):
        errors.append("unexpected analyzer operator attestation hash")

    bitrate = manifest.get("nominal_bitrate_configuration")
    expected_bitrate = {
        "status": "PASS",
        "arbitration_bitrate_bits_per_second": 1_000_000,
        "evidence_member": "bit-timing.png",
        "evidence_sha256": EXPECTED_SOURCE_HASHES["bit-timing.png"],
        "review_method": "human visual inspection of archived analyzer UI screenshot",
        "observed_ui_text": "CAN速率（仲裁域）=1M",
        "detailed_sample_point_and_waveform": "NOT_COVERED",
    }
    if bitrate != expected_bitrate:
        errors.append("analyzer nominal bitrate evidence mismatch")
    if not members["bit-timing.png"].startswith(b"\x89PNG\r\n\x1a\n"):
        errors.append("analyzer bit-timing evidence is not a PNG")

    expected_summary = {
        "warmup_seconds": 5,
        "duration_seconds": 180,
        "frames": 11_459,
        "event_gaps": 0,
        "channel_gaps": 0,
        "device_drop_total": 0,
        "measurement_queue_drops": 0,
        "measurement_ring_drops": 0,
        "host_acceptance": False,
        "external_analyzer_reconciliation": "PENDING",
    }
    for name, expected in expected_summary.items():
        if summary.get(name) != expected:
            errors.append(f"analyzer summary mismatch: {name}")
    if not 60 <= summary.get("frames_per_second", 0) < 1000:
        errors.append("analyzer summary must remain a low-rate run")

    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        for name in (
            "summary.json",
            "diagnostics.csv",
            "frames.csv",
            "analyzer-log.txt",
        ):
            (run_dir / name).write_bytes(members[name])
        recomputed = load_reconciler().reconcile(run_dir)
    if recomputed != recorded:
        errors.append("analyzer reconciliation replay mismatch")
    if manifest.get("reconciliation") != recorded:
        errors.append("analyzer manifest reconciliation mismatch")
    expected_reconciliation = {
        "status": "PASS_WITH_LIMITATION",
        "frame_reconciliation": "PASS",
        "record_order_reconciliation": "NOT_DISTINGUISHABLE_IDENTICAL_FRAMES",
        "timestamp_reconciliation": "PASS_WITH_LIMITATION",
        "high_rate_analyzer_coverage": False,
        "analyzer_timestamp_resolution_ms": 1,
        "analyzer_measurement_records": 11_459,
        "dut_frame_records": 11_459,
        "id_mismatches": 0,
        "dlc_mismatches": 0,
        "payload_mismatches": 0,
        "errors": [],
    }
    for name, expected in expected_reconciliation.items():
        if recorded.get(name) != expected:
            errors.append(f"analyzer reconciliation mismatch: {name}")
    if recorded.get("active_span_rate_difference_percent", 1) > 0.5:
        errors.append("analyzer/DUT active-span rate agreement is insufficient")
    firmware = manifest.get("firmware_evidence")
    if not isinstance(firmware, dict):
        errors.append("analyzer firmware evidence is missing")
    else:
        firmware_path = repository_file(
            root, firmware.get("path"), "analyzer firmware evidence", errors
        )
        if (
            firmware_path is not None
            and firmware.get("sha256") != sha256_file(firmware_path)
        ):
            errors.append("analyzer firmware evidence SHA-256 mismatch")

    boundary = evidence.get("evidence_boundary")
    if not isinstance(boundary, dict):
        errors.append("analyzer evidence boundary is missing")
        boundary = {}
    if boundary.get("statement") != EXPECTED_STATEMENT:
        errors.append("analyzer evidence statement mismatch")
    limitations = boundary.get("limitations")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "order permutations" in item
        for item in limitations
    ):
        errors.append("analyzer evidence must retain the identical-frame order limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "1 ms resolution" in item for item in limitations
    ):
        errors.append("analyzer evidence must retain the 1 ms timestamp limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "6000 frame/s" in item for item in limitations
    ):
        errors.append("analyzer evidence must retain the high-rate coverage limitation")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and "sample point" in item for item in limitations
    ):
        errors.append("analyzer evidence must retain the detailed bit-timing limitation")
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
        "PASS low-rate analyzer frame/content and nominal 1 Mbit/s reconciliation; "
        "timestamps retain explicit limitations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
