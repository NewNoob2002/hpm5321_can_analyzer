import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


usb = load_module("usb_validator", ROOT / "scripts/phase0/validate_usb_composite.py")
packager = load_module(
    "artifact_packager", ROOT / "scripts/phase0/package_current_artifact.py"
)


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

    def test_nonce_bound_capture_uses_archived_source_commit(self):
        capture = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-capture.txt"
        metadata = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-metadata.json"
        self.assertEqual(self.run_validator(capture, metadata).returncode, 0)

    def test_schema2_archived_capture_requires_valid_artifact_package(self):
        capture = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-capture.txt"
        metadata = json.loads(
            (
                ROOT
                / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-metadata.json"
            ).read_text()
        )
        attestation = json.loads(
            (
                ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-artifact.json"
            ).read_text()
        )
        attestation["schema"] = 2
        attestation["artifact_package"] = (
            "docs/evidence/phase0/does-not-exist.zip"
        )
        attestation["artifact_package_sha256"] = "0" * 64
        directory = ROOT / "docs/evidence/phase0"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=directory, delete=False
        ) as stream:
            json.dump(attestation, stream)
            attestation_path = Path(stream.name)
        try:
            metadata["artifact_attestation_path"] = str(
                attestation_path.relative_to(ROOT)
            )
            with tempfile.TemporaryDirectory() as temp:
                metadata_path = Path(temp) / "metadata.json"
                metadata_path.write_text(json.dumps(metadata))
                result = self.run_validator(capture, metadata_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("artifact attestation validation failed", result.stderr)
            self.assertIn("invalid artifact package", result.stderr)
        finally:
            attestation_path.unlink()

    def test_artifact_attestation_must_be_inside_repository(self):
        capture = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-capture.txt"
        metadata = json.loads(
            (
                ROOT
                / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-metadata.json"
            ).read_text()
        )
        source = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-artifact.json"
        with tempfile.TemporaryDirectory() as temporary:
            attestation = Path(temporary) / "artifact.json"
            attestation.write_bytes(source.read_bytes())
            metadata["artifact_attestation_path"] = str(attestation)
            metadata_path = Path(temporary) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            result = self.run_validator(capture, metadata_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid artifact attestation path", result.stderr)

    def test_artifact_attestation_symlink_is_rejected(self):
        capture = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-capture.txt"
        metadata = json.loads(
            (
                ROOT
                / "docs/evidence/phase0/T-CAN-013-ABI5-A504-adapter-metadata.json"
            ).read_text()
        )
        source = ROOT / "docs/evidence/phase0/T-CAN-013-ABI5-A504-artifact.json"
        directory = ROOT / "docs/evidence/phase0"
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            link = Path(temporary) / "artifact-link.json"
            link.symlink_to(source)
            metadata["artifact_attestation_path"] = link.relative_to(ROOT).as_posix()
            metadata_path = Path(temporary) / "metadata.json"
            metadata_path.write_text(json.dumps(metadata))
            result = self.run_validator(capture, metadata_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid artifact attestation path", result.stderr)

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
        self.rebuild = ROOT / "scripts/phase0/rebuild_current_artifact.sh"

    def run_validator(self, attestation: Path):
        env = os.environ.copy()
        return subprocess.run(
            [sys.executable, str(self.validator), str(attestation)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    @staticmethod
    def write_package(
        path: Path,
        package_manifest: dict,
        artifact_name: str,
        artifact_bytes: bytes,
        *,
        external_attr: int = 0o100644 << 16,
    ) -> None:
        manifest_bytes = (
            json.dumps(package_manifest, indent=2, sort_keys=True) + "\n"
        ).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in (
                ("package-manifest.json", manifest_bytes),
                (artifact_name, artifact_bytes),
            ):
                info = zipfile.ZipInfo(name, packager.FIXED_ZIP_TIME)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_STORED
                info.flag_bits = 0
                info.internal_attr = 0
                info.external_attr = external_attr
                archive.writestr(info, payload)

    def test_archived_artifact_attestation(self):
        self.assertEqual(self.run_validator(self.attestation).returncode, 0)

    def test_archived_artifact_requires_source_commit(self):
        data = json.loads(self.attestation.read_text())
        data.pop("source_commit")
        data["artifact_package"] = "docs/evidence/phase0/does-not-exist.zip"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(data))
            result = self.run_validator(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires a full source_commit", result.stderr)

    def test_archived_artifact_does_not_require_ignored_build_tree(self):
        build = ROOT / "build/review-mcan-tx"
        hidden = ROOT / "build/review-mcan-tx.validator-hidden"
        self.assertFalse(hidden.exists())
        moved = build.is_dir()
        if moved:
            build.rename(hidden)
        try:
            self.assertEqual(self.run_validator(self.attestation).returncode, 0)
        finally:
            if moved:
                hidden.rename(build)

    def test_packager_rejects_forged_build_definitions(self):
        data = json.loads(self.attestation.read_text())
        forged = dict(data["build_definitions"])
        forged["MCAN0_ACTIVE_TX"] = 0
        arguments = [
            "riscv32-unknown-elf-gcc",
            *(f"-D{name}={value}" for name, value in data["build_definitions"].items()),
            "-c",
            str(ROOT / packager.SOURCE_SUFFIX),
        ]
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            (build / "compile_commands.json").write_text(json.dumps([{
                "directory": str(build),
                "file": str(ROOT / packager.SOURCE_SUFFIX),
                "arguments": arguments,
            }]))
            with self.assertRaises(SystemExit) as context:
                packager.actual_build_definitions(build, forged)
        self.assertIn("build definition mismatch", str(context.exception))

    def test_sdk_commit_must_match_archived_lock_without_local_sdk(self):
        data = json.loads(self.attestation.read_text())
        package = ROOT / data["artifact_package"]
        with zipfile.ZipFile(package) as archive:
            package_manifest = json.loads(archive.read("package-manifest.json"))
            artifact_bytes = archive.read(data["artifact"])
        data["sdk_commit"] = "0" * 40
        package_manifest["sdk_commit"] = "0" * 40
        directory = ROOT / "docs/evidence/phase0"
        with tempfile.TemporaryDirectory(dir=directory) as temp:
            temp_path = Path(temp)
            package_path = temp_path / "artifact.zip"
            self.write_package(
                package_path,
                package_manifest,
                data["artifact"],
                artifact_bytes,
            )
            data["artifact_package"] = str(package_path.relative_to(ROOT))
            data["artifact_package_sha256"] = hashlib.sha256(
                package_path.read_bytes()
            ).hexdigest()
            attestation = temp_path / "artifact.json"
            attestation.write_text(json.dumps(data))
            env_value = os.environ.pop("HPM_SDK_BASE", None)
            try:
                result = self.run_validator(attestation)
            finally:
                if env_value is not None:
                    os.environ["HPM_SDK_BASE"] = env_value
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SDK commit does not match archived lock", result.stderr)

    def test_unsafe_artifact_member_rejected(self):
        data = json.loads(self.attestation.read_text())
        data["artifact"] = "../unsafe.elf"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(data))
            result = self.run_validator(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid artifact member", result.stderr)

    def test_packager_rejects_output_outside_repository(self):
        with self.assertRaises(SystemExit) as context:
            packager.repository_output("../escaped.zip", "artifact package")
        self.assertIn("invalid artifact package", str(context.exception))

    def test_packager_rejects_output_symlink(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            target = directory / "target.zip"
            target.write_bytes(b"existing")
            link = directory / "artifact.zip"
            link.symlink_to(target)
            with self.assertRaises(SystemExit) as context:
                packager.repository_output(
                    link.relative_to(ROOT).as_posix(), "artifact package"
                )
        self.assertIn("must not be a symlink", str(context.exception))

    def test_sdk_dirty_package_is_rejected(self):
        data = json.loads(self.attestation.read_text())
        package = ROOT / data["artifact_package"]
        with zipfile.ZipFile(package) as archive:
            package_manifest = json.loads(archive.read("package-manifest.json"))
            artifact_bytes = archive.read(data["artifact"])
        package_manifest["sdk_dirty"] = True
        directory = ROOT / "docs/evidence/phase0"
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            temp = Path(temporary)
            package_path = temp / "artifact.zip"
            self.write_package(
                package_path, package_manifest, data["artifact"], artifact_bytes
            )
            data["artifact_package"] = package_path.relative_to(ROOT).as_posix()
            data["artifact_package_sha256"] = hashlib.sha256(
                package_path.read_bytes()
            ).hexdigest()
            attestation = temp / "artifact.json"
            attestation.write_text(json.dumps(data))
            result = self.run_validator(attestation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SDK worktree must be clean", result.stderr)

    def test_rebuild_rejects_preexisting_ignored_python_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = Path(temporary)
            (sdk / ".gitignore").write_text("__pycache__/\n")
            bytecode = sdk / "scripts/ide/__pycache__/generator.pyc"
            bytecode.parent.mkdir(parents=True)
            bytecode.write_bytes(b"untrusted bytecode")
            env = os.environ.copy()
            env["HPM_SDK_BASE"] = str(sdk)
            result = subprocess.run(
                ["sh", str(self.rebuild)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SDK worktree contains Python bytecode", result.stderr)

    def test_rebuild_disables_python_bytecode_generation(self):
        script = self.rebuild.read_text()
        self.assertEqual(script.count("PYTHONDONTWRITEBYTECODE=1"), 2)
        self.assertNotIn("-exec rm -rf", script)

    def test_package_member_dos_attributes_are_rejected(self):
        data = json.loads(self.attestation.read_text())
        package = ROOT / data["artifact_package"]
        with zipfile.ZipFile(package) as archive:
            package_manifest = json.loads(archive.read("package-manifest.json"))
            artifact_bytes = archive.read(data["artifact"])
        directory = ROOT / "docs/evidence/phase0"
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            temp = Path(temporary)
            package_path = temp / "artifact.zip"
            self.write_package(
                package_path,
                package_manifest,
                data["artifact"],
                artifact_bytes,
                external_attr=(0o100644 << 16) | 0x01,
            )
            data["artifact_package"] = package_path.relative_to(ROOT).as_posix()
            data["artifact_package_sha256"] = hashlib.sha256(
                package_path.read_bytes()
            ).hexdigest()
            attestation = temp / "artifact.json"
            attestation.write_text(json.dumps(data))
            result = self.run_validator(attestation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact package member metadata mismatch", result.stderr)

    def test_stale_artifact_hash_rejected(self):
        data = json.loads(self.attestation.read_text())
        data["elf_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(data))
            result = self.run_validator(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("artifact SHA-256 mismatch", result.stderr)

    def test_invalid_external_capture_status_rejected(self):
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
