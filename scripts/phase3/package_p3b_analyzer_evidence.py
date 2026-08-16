#!/usr/bin/env python3
"""Package immutable low-rate independent analyzer reconciliation evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PACKAGE_MEMBERS = (
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
)
RUN_FILES = PACKAGE_MEMBERS[1:10]


def fail(message: str) -> None:
    raise SystemExit(message)


def normalized_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value:
        fail(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        fail(f"invalid {label}")
    if str(path) != value:
        fail(f"invalid {label}")
    return value


def repository_output(relative: str, label: str) -> Path:
    path = ROOT / safe_relative_path(relative, label)
    try:
        path.parent.resolve(strict=True).relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError):
        fail(f"invalid {label}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        fail(f"{label} must be a regular file or absent")
    return path


def regular_file(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(ROOT.resolve())
    except (FileNotFoundError, ValueError):
        fail(f"missing or invalid {label}: {path}")
    if path.is_symlink() or not resolved.is_file():
        fail(f"{label} must be a regular repository file")
    return resolved


def json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} root must be an object")
    return value


def command_output(command: list[str], label: str) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"unable to read {label}: {result.stderr.strip()}")
    return result.stdout.strip()


def load_reconciler(path: Path):
    spec = importlib.util.spec_from_file_location("p3b_analyzer_reconciler", path)
    if spec is None or spec.loader is None:
        fail("unable to load analyzer reconciler")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def file_reference(data: bytes) -> dict[str, Any]:
    return {"sha256": sha256_bytes(data), "size": len(data)}


def write_package(path: Path, data: dict[str, bytes]) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.comment = b""
            for name in PACKAGE_MEMBERS:
                archive.writestr(zip_info(name), data[name])
        temporary.replace(path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_bytes(normalized_json(value))
        temporary.replace(path)
        path.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=ROOT
        / "artifacts/hil-2026-08-15/T-CAN-1M-1MS-ANALYZER-RECON-123111",
    )
    parser.add_argument(
        "--capture-anchor",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-capture-tool-anchor-2026-08-15.json",
    )
    parser.add_argument(
        "--capture-source",
        type=Path,
        default=ROOT / "host/crates/core/examples/can_hil_capture.rs",
    )
    parser.add_argument(
        "--capture-binary",
        type=Path,
        default=ROOT / "host/target/release/examples/can_hil_capture",
    )
    parser.add_argument(
        "--reconciler",
        type=Path,
        default=ROOT / "scripts/phase3/reconcile_p3b_analyzer.py",
    )
    parser.add_argument(
        "--firmware-evidence",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json",
    )
    parser.add_argument(
        "--operator-attestation",
        type=Path,
        default=ROOT
        / "docs/evidence/phase3/P3B-independent-analyzer-capability-2026-08-15.txt",
    )
    parser.add_argument(
        "--package",
        default="docs/evidence/phase3/P3B-HIL-analyzer-low-rate-2026-08-15.zip",
    )
    parser.add_argument(
        "--evidence",
        default="docs/evidence/phase3/P3B-HIL-analyzer-low-rate-evidence-2026-08-15.json",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    try:
        run_dir.relative_to(ROOT.resolve())
    except ValueError:
        fail("run directory must be inside the repository")

    reconciler = regular_file(args.reconciler, "analyzer reconciler")
    reconciliation = load_reconciler(reconciler).reconcile(run_dir)
    if reconciliation.get("status") != "PASS_WITH_LIMITATION":
        fail(f"analyzer reconciliation failed: {reconciliation.get('errors')}")
    reconciliation_path = run_dir / "analyzer-reconciliation.json"
    reconciliation_path.write_bytes(normalized_json(reconciliation))

    files = {
        name: regular_file(run_dir / name, f"analyzer run {name}").read_bytes()
        for name in RUN_FILES
    }
    summary = json_object(files["summary.json"], "analyzer run summary")
    recorded = json_object(
        files["analyzer-reconciliation.json"], "analyzer reconciliation"
    )
    if recorded != reconciliation:
        fail("recorded analyzer reconciliation differs from replay")
    if summary.get("warmup_seconds") != 5 or summary.get("duration_seconds") != 180:
        fail("analyzer run must use the recorded 5+180 second profile")
    if summary.get("frames") != 11_459:
        fail("unexpected analyzer run frame count")
    if summary.get("frames_per_second", 0) >= 1000:
        fail("analyzer evidence must remain a low-rate export-capable run")
    if summary.get("host_acceptance") is not False:
        fail("low-rate analyzer run must not claim frozen high-load acceptance")

    capture_anchor = regular_file(args.capture_anchor, "capture tool anchor")
    capture_source = regular_file(args.capture_source, "capture source")
    capture_binary = regular_file(args.capture_binary, "capture binary")
    firmware_evidence = regular_file(args.firmware_evidence, "firmware evidence")
    operator_attestation = regular_file(
        args.operator_attestation, "operator attestation"
    )
    package_path = repository_output(args.package, "analyzer package")
    evidence_path = repository_output(args.evidence, "analyzer evidence")

    head = command_output(["git", "rev-parse", "HEAD"], "source commit")
    source_dirty = bool(command_output(["git", "status", "--porcelain"], "source status"))
    compiler = command_output(["rustc", "--version"], "Rust compiler")
    capture_source_bytes = capture_source.read_bytes()
    capture_binary_bytes = capture_binary.read_bytes()
    capture_anchor_bytes = capture_anchor.read_bytes()
    capture_anchor_value = json_object(capture_anchor_bytes, "capture tool anchor")
    expected_capture_source = {
        "commit": head,
        "dirty": source_dirty,
        "member": "capture/can_hil_capture.rs",
        "sha256": sha256_bytes(capture_source_bytes),
        "size": len(capture_source_bytes),
    }
    expected_capture_binary = {
        "member": "capture/can_hil_capture",
        "sha256": sha256_bytes(capture_binary_bytes),
        "size": len(capture_binary_bytes),
    }
    if (
        capture_anchor_value.get("schema") != 1
        or capture_anchor_value.get("evidence_id")
        != "P3B-capture-tool-anchor-2026-08-15"
        or capture_anchor_value.get("phase") != "P3B"
        or capture_anchor_value.get("source") != expected_capture_source
        or capture_anchor_value.get("binary") != expected_capture_binary
        or capture_anchor_value.get("compiler") != compiler
    ):
        fail("capture tool does not match immutable anchor")
    reconciler_bytes = reconciler.read_bytes()
    operator_bytes = operator_attestation.read_bytes()
    file_references = {name: file_reference(data) for name, data in files.items()}

    manifest = {
        "schema": 1,
        "evidence_id": "P3B-HIL-analyzer-low-rate-2026-08-15",
        "phase": "P3B",
        "test": "independent analyzer low-rate reconciliation",
        "command": (
            "cd host && cargo run -p hpm-usb-can-core --release "
            "--example can_hil_capture -- 5 180 "
            "../artifacts/hil-2026-08-15/"
            "T-CAN-1M-1MS-ANALYZER-RECON-123111"
        ),
        "result": "PASS_WITH_LIMITATION",
        "capture_tool": {
            "source_commit": head,
            "source_dirty": source_dirty,
            "anchor_member": "capture/capture-tool-anchor.json",
            "anchor_sha256": sha256_bytes(capture_anchor_bytes),
            "source_member": "capture/can_hil_capture.rs",
            "source_sha256": sha256_bytes(capture_source_bytes),
            "binary_member": "capture/can_hil_capture",
            "binary_sha256": sha256_bytes(capture_binary_bytes),
            "binary_size": len(capture_binary_bytes),
            "compiler": compiler,
        },
        "firmware_evidence": {
            "path": firmware_evidence.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(firmware_evidence),
        },
        "reconciliation_tool": {
            "member": "reconcile/reconcile_p3b_analyzer.py",
            "sha256": sha256_bytes(reconciler_bytes),
        },
        "operator_attestation": {
            "member": "operator-attestation.txt",
            "sha256": sha256_bytes(operator_bytes),
        },
        "files": file_references,
        "nominal_bitrate_configuration": {
            "status": "PASS",
            "arbitration_bitrate_bits_per_second": 1_000_000,
            "evidence_member": "bit-timing.png",
            "evidence_sha256": sha256_bytes(files["bit-timing.png"]),
            "review_method": "human visual inspection of archived analyzer UI screenshot",
            "observed_ui_text": "CAN速率（仲裁域）=1M",
            "detailed_sample_point_and_waveform": "NOT_COVERED",
        },
        "reconciliation": reconciliation,
    }
    package_data = {
        "run-manifest.json": normalized_json(manifest),
        **files,
        "capture/capture-tool-anchor.json": capture_anchor_bytes,
        "capture/can_hil_capture.rs": capture_source_bytes,
        "capture/can_hil_capture": capture_binary_bytes,
        "reconcile/reconcile_p3b_analyzer.py": reconciler_bytes,
        "operator-attestation.txt": operator_bytes,
    }
    write_package(package_path, package_data)

    evidence = {
        "schema": 1,
        "evidence_id": "P3B-HIL-analyzer-low-rate-evidence-2026-08-15",
        "phase": "P3B",
        "status": "PASS_WITH_LIMITATION",
        "package": {
            "path": package_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(package_path),
            "size": package_path.stat().st_size,
            "members": list(PACKAGE_MEMBERS),
            "run_manifest_sha256": sha256_bytes(package_data["run-manifest.json"]),
        },
        "outcomes": {
            "frame_count_and_content_reconciliation": "PASS",
            "record_order_reconciliation": "NOT_DISTINGUISHABLE_IDENTICAL_FRAMES",
            "coarse_timestamp_and_rate_reconciliation": "PASS_WITH_LIMITATION",
            "nominal_1_mbit_configuration_reconciliation": "PASS",
            "high_rate_analyzer_timestamp_coverage": "NOT_CLAIMED",
            "detailed_sample_point_and_waveform_reconciliation": "NOT_COVERED",
        },
        "evidence_boundary": {
            "statement": (
                "The export-capable approximately 64 frame/s analyzer window exactly "
                "matches all 11459 DUT frames by count, identifier, DLC, and payload. "
                "Because every frame is identical, independent order permutations are "
                "not distinguishable. Its active-span rate agrees with the DUT capture, and the "
                "archived analyzer configuration screenshot records a 1 Mbit/s "
                "arbitration bitrate."
            ),
            "limitations": reconciliation["limitations"]
            + [
                "The configuration screenshot proves the selected nominal arbitration bitrate, not electrical waveform shape, sample point, or oscillator tolerance."
            ],
        },
    }
    write_json(evidence_path, evidence)
    print(
        "PASS analyzer=PASS_WITH_LIMITATION frames=11459 bitrate=1000000 "
        f"package={evidence['package']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
