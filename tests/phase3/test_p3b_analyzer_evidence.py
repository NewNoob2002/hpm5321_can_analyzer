from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(
    "docs/evidence/phase3/P3B-HIL-analyzer-low-rate-evidence-2026-08-15.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_analyzer_evidence.py"
    spec = importlib.util.spec_from_file_location("p3b_analyzer_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bAnalyzerEvidenceTests(unittest.TestCase):
    def current_evidence(self) -> dict:
        return json.loads((ROOT / EVIDENCE).read_text())

    def write_evidence(self, directory: Path, value: dict) -> Path:
        path = directory / "evidence.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def rewrite_package(
        self,
        directory: Path,
        evidence: dict,
        mutate,
    ) -> None:
        source_path = ROOT / evidence["package"]["path"]
        package_path = directory / "analyzer.zip"
        with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(
            package_path, "w"
        ) as target:
            for info in source.infolist():
                target.writestr(info, mutate(info.filename, source.read(info.filename)))
        evidence["package"]["path"] = package_path.relative_to(ROOT).as_posix()
        evidence["package"]["sha256"] = hashlib.sha256(
            package_path.read_bytes()
        ).hexdigest()
        evidence["package"]["size"] = package_path.stat().st_size

    def test_current_evidence_passes(self):
        self.assertEqual(validator.validate(ROOT, EVIDENCE), [])

    def test_overall_or_high_rate_claim_cannot_be_upgraded(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            evidence["status"] = "PASS"
            evidence["outcomes"]["high_rate_analyzer_timestamp_coverage"] = "PASS"
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "analyzer evidence must remain PASS_WITH_LIMITATION", errors
        )
        self.assertIn("analyzer evidence outcomes mismatch", errors)

    def test_tampered_analyzer_log_is_rejected_with_updated_package_hash(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()

            def mutate(name: str, data: bytes) -> bytes:
                if name == "analyzer-log.txt":
                    return data.replace(b"Send[7FF]", b"Send[123]", 1)
                return data

            self.rewrite_package(directory, evidence, mutate)
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "unexpected immutable analyzer source hash: analyzer-log.txt", errors
        )
        self.assertIn(
            "analyzer member reference mismatch: analyzer-log.txt", errors
        )

    def test_tampered_bitrate_screenshot_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()

            def mutate(name: str, data: bytes) -> bytes:
                return data + b"x" if name == "bit-timing.png" else data

            self.rewrite_package(directory, evidence, mutate)
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "unexpected immutable analyzer source hash: bit-timing.png", errors
        )
        self.assertIn("analyzer member reference mismatch: bit-timing.png", errors)

    def test_detailed_bit_timing_cannot_be_claimed_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()

            def mutate(name: str, data: bytes) -> bytes:
                if name != "run-manifest.json":
                    return data
                manifest = json.loads(data)
                manifest["nominal_bitrate_configuration"][
                    "detailed_sample_point_and_waveform"
                ] = "PASS"
                return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

            self.rewrite_package(directory, evidence, mutate)
            package_path = ROOT / evidence["package"]["path"]
            with zipfile.ZipFile(package_path) as archive:
                evidence["package"]["run_manifest_sha256"] = hashlib.sha256(
                    archive.read("run-manifest.json")
                ).hexdigest()
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn("analyzer nominal bitrate evidence mismatch", errors)

    def test_reader_visible_statement_cannot_contradict_structured_outcomes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            evidence["evidence_boundary"]["statement"] = (
                "This independently proves 6000 frame/s with sub-millisecond "
                "timestamps and complete electrical bit timing."
            )
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn("analyzer evidence statement mismatch", errors)

    def test_capture_source_and_binary_cannot_be_replaced_with_updated_manifest(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            replacement_source = b"fn main() { panic!(\"tampered\"); }\n"
            replacement_binary = b"tampered capture binary"

            def mutate(name: str, data: bytes) -> bytes:
                if name == "capture/can_hil_capture.rs":
                    return replacement_source
                if name == "capture/can_hil_capture":
                    return replacement_binary
                if name != "run-manifest.json":
                    return data
                manifest = json.loads(data)
                manifest["capture_tool"]["source_sha256"] = hashlib.sha256(
                    replacement_source
                ).hexdigest()
                manifest["capture_tool"]["binary_sha256"] = hashlib.sha256(
                    replacement_binary
                ).hexdigest()
                manifest["capture_tool"]["binary_size"] = len(replacement_binary)
                return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

            self.rewrite_package(directory, evidence, mutate)
            package_path = ROOT / evidence["package"]["path"]
            with zipfile.ZipFile(package_path) as archive:
                evidence["package"]["run_manifest_sha256"] = hashlib.sha256(
                    archive.read("run-manifest.json")
                ).hexdigest()
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "analyzer capture source does not match immutable anchor", errors
        )
        self.assertIn(
            "analyzer capture binary does not match immutable anchor", errors
        )

    def test_auxiliary_member_cannot_be_changed_with_updated_manifest_reference(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            replacement = b"host_ns,ping\n1,tampered\n"

            def mutate(name: str, data: bytes) -> bytes:
                if name == "pings.csv":
                    return replacement
                if name != "run-manifest.json":
                    return data
                manifest = json.loads(data)
                manifest["files"]["pings.csv"] = {
                    "sha256": hashlib.sha256(replacement).hexdigest(),
                    "size": len(replacement),
                }
                return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

            self.rewrite_package(directory, evidence, mutate)
            package_path = ROOT / evidence["package"]["path"]
            with zipfile.ZipFile(package_path) as archive:
                evidence["package"]["run_manifest_sha256"] = hashlib.sha256(
                    archive.read("run-manifest.json")
                ).hexdigest()
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "unexpected immutable analyzer source hash: pings.csv", errors
        )


if __name__ == "__main__":
    unittest.main()
