from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.phase3.firmware_provenance import verified_firmware_manifest


def write_manifest(root: Path, elf: bytes = b"elf", binary: bytes = b"bin") -> Path:
    build = root / "build"
    output = build / "output"
    output.mkdir(parents=True)
    artifacts = {}
    for name, content in (("demo.elf", elf), ("demo.bin", binary)):
        path = output / name
        path.write_bytes(content)
        artifacts[name] = {
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = build / "build-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "preset": "test",
                "source_revision": "a" * 40,
                "source_dirty": False,
                "sdk_commit": "b" * 40,
                "compiler": "test-gcc",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return manifest


class FirmwareProvenanceTests(unittest.TestCase):
    def test_verifies_manifest_and_artifact_hashes_outside_repository(self) -> None:
        with (
            tempfile.TemporaryDirectory() as repository,
            tempfile.TemporaryDirectory() as build,
        ):
            manifest = write_manifest(Path(build))

            result = verified_firmware_manifest(manifest, Path(repository))

            self.assertEqual(result["source_revision"], "a" * 40)
            self.assertEqual(result["path"], str(manifest))
            self.assertTrue(result["verified_artifacts"]["demo.elf"]["verified"])
            self.assertFalse(result["device_attested"])

    def test_rejects_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "schema must be 1"):
                verified_firmware_manifest(manifest, Path(temporary))

    def test_rejects_artifact_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_manifest(root)
            (manifest.parent / "output" / "demo.elf").write_bytes(b"changed")

            with self.assertRaisesRegex(RuntimeError, "does not match manifest"):
                verified_firmware_manifest(manifest, root)


if __name__ == "__main__":
    unittest.main()
