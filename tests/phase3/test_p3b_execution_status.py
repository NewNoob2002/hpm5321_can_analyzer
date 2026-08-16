from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("docs/evidence/phase3/P3B-HIL-execution-status-2026-08-14.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_execution_status.py"
    spec = importlib.util.spec_from_file_location("p3b_execution_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


def load_packager():
    path = ROOT / "scripts/phase3/package_p3b_execution_status.py"
    spec = importlib.util.spec_from_file_location("p3b_execution_packager", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = load_packager()


class P3bExecutionStatusTests(unittest.TestCase):
    def current_manifest(self) -> dict:
        return json.loads((ROOT / MANIFEST).read_text())

    def write_manifest(self, directory: Path, value: dict) -> Path:
        path = directory / "status.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def test_current_status_passes(self):
        self.assertEqual(validator.validate(ROOT, MANIFEST), [])

    def test_cannot_claim_qualification_or_open_p4e(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["qualification_status"] = "PASS"
            manifest["p4e_gate"] = "OPEN"
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("P3B qualification must remain PARTIAL", errors)
        self.assertIn("P4E gate must remain BLOCKED", errors)

    def test_tampered_no_load_transcript_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            transcript = directory / "ping.txt"
            transcript.write_bytes(
                (
                    ROOT
                    / "docs/evidence/phase3/P3B-USB-ping-soak-no-can-load-2026-08-14.txt"
                ).read_bytes()
                + b"\nTAMPERED\n"
            )
            manifest = self.current_manifest()
            manifest["no_can_load_baselines"]["usb_ping_soak"]["transcript"][
                "path"
            ] = transcript.relative_to(ROOT).as_posix()
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn(
            "no-load baseline transcript SHA-256 mismatch: usb_ping_soak", errors
        )

    def test_malformed_nested_types_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["frozen_profile"]["required_command"] = 1
            manifest["frozen_profile"]["blocked_reason"] = None
            manifest["evidence_boundary"]["pending"] = [{}]
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("frozen profile command must be a string", errors)
        self.assertIn("status blocked reason must identify zero CAN frames", errors)
        self.assertIn("execution evidence boundary pending set mismatch", errors)

    def test_nested_firmware_evidence_is_fully_validated(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            nested = json.loads(
                (
                    ROOT
                    / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json"
                ).read_text()
            )
            nested["program_verify"]["transcript"]["sha256"] = "0" * 64
            nested_path = directory / "firmware-evidence.json"
            nested_path.write_text(json.dumps(nested, indent=2, sort_keys=True) + "\n")
            manifest = self.current_manifest()
            manifest["firmware_evidence"]["path"] = nested_path.relative_to(
                ROOT
            ).as_posix()
            manifest["firmware_evidence"]["sha256"] = hashlib.sha256(
                nested_path.read_bytes()
            ).hexdigest()
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("firmware evidence: program transcript SHA-256 mismatch", errors)

    def test_packager_rejects_invalid_nested_firmware_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            preflight_dir = directory / "preflight"
            preflight_dir.mkdir()
            source_package = (
                ROOT / self.current_manifest()["preflight"]["package"]["path"]
            )
            with zipfile.ZipFile(source_package) as source:
                for name in packager.PREFLIGHT_MEMBERS:
                    (preflight_dir / name).write_bytes(source.read(name))
            nested = json.loads(
                (
                    ROOT
                    / "docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json"
                ).read_text()
            )
            nested["program_verify"]["transcript"]["sha256"] = "0" * 64
            nested_path = directory / "firmware-evidence.json"
            nested_path.write_text(json.dumps(nested, indent=2, sort_keys=True) + "\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3/package_p3b_execution_status.py"),
                    "--firmware-evidence",
                    str(nested_path),
                    "--preflight-dir",
                    str(preflight_dir),
                    "--package",
                    f"{directory.name}/preflight.zip",
                    "--status",
                    f"{directory.name}/status.json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("firmware evidence validation failed", result.stderr)

    def test_input_must_be_a_regular_repository_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary) / "outside.txt"
            outside.write_text("outside")
            with self.assertRaises(SystemExit) as context:
                packager.regular_file(outside, "hardware inventory transcript")
        self.assertIn("must be a regular repository file", str(context.exception))

    def test_package_member_dos_attributes_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_package = ROOT / manifest["preflight"]["package"]["path"]
            package = directory / "preflight.zip"
            with zipfile.ZipFile(source_package) as source, zipfile.ZipFile(
                package, "w"
            ) as target:
                for source_info in source.infolist():
                    info = zipfile.ZipInfo(source_info.filename, source_info.date_time)
                    info.create_system = source_info.create_system
                    info.compress_type = source_info.compress_type
                    info.flag_bits = source_info.flag_bits
                    info.internal_attr = source_info.internal_attr
                    info.external_attr = source_info.external_attr | 0x01
                    target.writestr(info, source.read(source_info.filename))
            manifest["preflight"]["package"]["path"] = package.relative_to(
                ROOT
            ).as_posix()
            manifest["preflight"]["package"]["sha256"] = hashlib.sha256(
                package.read_bytes()
            ).hexdigest()
            manifest["preflight"]["package"]["size"] = package.stat().st_size
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertTrue(
            any("preflight package member metadata mismatch" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
