import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


usb = load_module("usb_validator", ROOT / "scripts/phase0/validate_usb_composite.py")


class UsbModelTests(unittest.TestCase):
    def test_planned_variants(self):
        for variant in usb.VARIANTS:
            usb.validate(variant, 16)

    def test_duplicate_address_rejected(self):
        class Invalid:
            name = "duplicate"
            endpoints = ((0x81, "a"), (0x81, "b"))
            interfaces = ("vendor",)
            cdc = False
            dfu = False

        with self.assertRaises(usb.ValidationError):
            usb.validate(Invalid(), 16)

    def test_capacity_rejected_without_nibble_truncation_bug(self):
        with self.assertRaises(usb.ValidationError):
            usb.validate(usb.VARIANTS[1], 3)


class CanCaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture = ROOT / "docs/evidence/phase0/T-CAN-EXT-002-adapter-capture.txt"
        self.metadata = ROOT / "docs/evidence/phase0/T-CAN-EXT-002-adapter-metadata.json"
        self.validator = ROOT / "scripts/phase0/validate_can_capture.py"

    def run_validator(self, capture: Path, metadata: Path):
        return subprocess.run(
            [sys.executable, str(self.validator), "--metadata", str(metadata), str(capture)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_known_capture(self):
        self.assertEqual(self.run_validator(self.capture, self.metadata).returncode, 0)

    def test_non_monotonic_timestamps_rejected(self):
        lines = self.capture.read_text().splitlines()
        lines[1] = lines[1].replace("10:33:18.986", "10:33:18.983")
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.txt"
            capture.write_text("\n".join(lines) + "\n")
            metadata = json.loads(self.metadata.read_text())
            metadata["capture_sha256"] = hashlib.sha256(capture.read_bytes()).hexdigest()
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            result = self.run_validator(capture, metadata_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("timestamps are not strictly increasing", result.stderr)

    def test_wrong_frame_metadata_rejected(self):
        metadata = json.loads(self.metadata.read_text())
        metadata["protocol"] = "can-fd"
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            self.assertNotEqual(self.run_validator(self.capture, metadata_path).returncode, 0)

    def test_capture_hash_mismatch_rejected(self):
        lines = self.capture.read_text().splitlines()
        lines[-1] = lines[-1].replace("00 00 00 63", "00 00 00 62")
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "capture.txt"
            capture.write_text("\n".join(lines) + "\n")
            self.assertNotEqual(self.run_validator(capture, self.metadata).returncode, 0)

    def test_historical_capture_does_not_require_ignored_elf(self):
        metadata = json.loads(self.metadata.read_text())
        metadata.pop("elf_path", None)
        metadata.pop("elf_sha256", None)
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            self.assertEqual(self.run_validator(self.capture, metadata_path).returncode, 0)

    def test_historical_capture_cannot_be_relabelled_manifest_bound(self):
        metadata = json.loads(self.metadata.read_text())
        manifest = ROOT / "docs/evidence/phase0/T-CAN-EXT-source-manifest.sha256"
        metadata["provenance_status"] = "manifest-bound"
        metadata["source_manifest_path"] = str(manifest.relative_to(ROOT))
        metadata["source_manifest_sha256"] = hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            result = self.run_validator(self.capture, metadata_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported provenance_status", result.stderr)

    def test_abi_v4_capture_remains_explicitly_unbound(self):
        capture = ROOT / "docs/evidence/phase0/T-CAN-013-ABI4-adapter-capture.txt"
        metadata = ROOT / "docs/evidence/phase0/T-CAN-013-ABI4-adapter-metadata.json"
        self.assertEqual(self.run_validator(capture, metadata).returncode, 0)

    def test_historical_capture_cannot_use_current_nonce_attestation(self):
        if "HPM_SDK_BASE" not in os.environ:
            self.skipTest("HPM_SDK_BASE is required for SDK revision validation")
        capture = self.capture
        current = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-metadata.json"
        metadata = json.loads(current.read_text())
        metadata["capture_sha256"] = hashlib.sha256(capture.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            result = self.run_validator(capture, metadata_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ID or payload mismatch", result.stderr)


class CurrentArtifactTests(unittest.TestCase):
    def setUp(self):
        self.attestation = ROOT / "docs/evidence/phase0/T-CAN-TX-current-artifact.json"
        self.validator = ROOT / "scripts/phase0/validate_current_artifact.py"

    def run_validator(self, attestation: Path):
        env = os.environ.copy()
        return subprocess.run(
            [sys.executable, str(self.validator), str(attestation)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_current_artifact_attestation(self):
        if "HPM_SDK_BASE" not in os.environ:
            self.skipTest("HPM_SDK_BASE is required for SDK revision validation")
        self.assertEqual(self.run_validator(self.attestation).returncode, 0)

    def test_stale_artifact_hash_rejected(self):
        if "HPM_SDK_BASE" not in os.environ:
            self.skipTest("HPM_SDK_BASE is required for SDK revision validation")
        data = json.loads(self.attestation.read_text())
        data["elf_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(data))
            result = self.run_validator(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("artifact SHA-256 mismatch", result.stderr)

    def test_invalid_external_capture_status_rejected(self):
        if "HPM_SDK_BASE" not in os.environ:
            self.skipTest("HPM_SDK_BASE is required for SDK revision validation")
        data = json.loads(self.attestation.read_text())
        data["external_capture_status"] = "made-up-pass"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(data))
            result = self.run_validator(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid external_capture_status", result.stderr)


if __name__ == "__main__":
    unittest.main()
