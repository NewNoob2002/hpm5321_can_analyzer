from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("docs/evidence/phase3/P3B-HIL-firmware-evidence-2026-08-14.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_hil_firmware_evidence.py"
    spec = importlib.util.spec_from_file_location("hil_firmware_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


def load_packager():
    path = ROOT / "scripts/phase3/package_hil_firmware_evidence.py"
    spec = importlib.util.spec_from_file_location("hil_firmware_packager", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = load_packager()


class HilFirmwareEvidenceTests(unittest.TestCase):
    def write_manifest(self, directory: Path, value: dict) -> Path:
        path = directory / "evidence.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def current_manifest(self) -> dict:
        return json.loads((ROOT / MANIFEST).read_text())

    def test_current_evidence_passes(self):
        self.assertEqual(validator.validate(ROOT, MANIFEST), [])

    def test_missing_source_commit_is_reported_before_missing_package(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            del manifest["source"]["commit"]
            manifest["package"]["path"] = f"{directory.name}/missing.zip"
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertGreaterEqual(len(errors), 2)
        self.assertEqual(errors[0], "evidence requires a full source commit")
        self.assertIn("invalid or missing firmware package", errors[-1])

    def test_tampered_program_transcript_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            transcript = directory / "program.txt"
            transcript.write_bytes(
                (
                    ROOT
                    / "docs/evidence/phase3/P3B-HIL-flash-jlink-2026-08-14.txt"
                ).read_bytes()
                + b"\nTAMPERED\n"
            )
            manifest = self.current_manifest()
            manifest["program_verify"]["transcript"]["path"] = transcript.relative_to(
                ROOT
            ).as_posix()
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("program transcript SHA-256 mismatch", errors)

    def test_tampered_package_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            package = directory / "firmware.zip"
            package.write_bytes(
                (
                    ROOT / "docs/evidence/phase3/P3B-HIL-firmware-afbf243.zip"
                ).read_bytes()
                + b"TAMPERED"
            )
            manifest = self.current_manifest()
            manifest["package"]["path"] = package.relative_to(ROOT).as_posix()
            manifest["package"]["size"] = package.stat().st_size
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("firmware package SHA-256 mismatch", errors)

    def test_p4e_gate_cannot_be_opened_by_this_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["qualification_status"] = "PASS"
            manifest["p4e_gate"] = "OPEN"
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("P3B qualification must remain PARTIAL", errors)
        self.assertIn("P4E gate must remain BLOCKED", errors)

    def test_malformed_nested_types_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["firmware"]["demo.elf"] = "not-an-object"
            manifest["evidence_boundary"]["pending"] = [{}]
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("firmware evidence mismatch: demo.elf", errors)
        self.assertIn("evidence boundary pending set mismatch", errors)

    def test_input_must_be_a_regular_repository_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary) / "outside.txt"
            outside.write_text("outside")
            with self.assertRaises(SystemExit) as context:
                packager.regular_file(outside, "program transcript")
        self.assertIn("must be a regular repository file", str(context.exception))

    def test_package_member_dos_attributes_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_package = ROOT / manifest["package"]["path"]
            package = directory / "firmware.zip"
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
            manifest["package"]["path"] = package.relative_to(ROOT).as_posix()
            manifest["package"]["sha256"] = hashlib.sha256(
                package.read_bytes()
            ).hexdigest()
            manifest["package"]["size"] = package.stat().st_size
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertTrue(
            any("firmware package member metadata mismatch" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
