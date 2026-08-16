from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("docs/evidence/phase3/P3B-HIL-load-status-2026-08-15.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_load_evidence.py"
    spec = importlib.util.spec_from_file_location("p3b_load_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bLoadEvidenceTests(unittest.TestCase):
    def current_manifest(self) -> dict:
        return json.loads((ROOT / MANIFEST).read_text())

    def write_manifest(self, directory: Path, value: dict) -> Path:
        path = directory / "status.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def test_current_load_status_passes(self):
        self.assertEqual(validator.validate(ROOT, MANIFEST), [])

    def test_missing_large_zip_uses_fail_closed_external_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_bytes(
                (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_bytes()
            )
            run = self.current_manifest()["runs"]["diagnostic_10_min"]
            errors: list[str] = []
            members, frames, artifact = validator.validate_package(
                root,
                run["package"],
                validator.DIAGNOSTIC_MEMBERS,
                "diagnostic run",
                errors,
            )
        self.assertEqual(errors, [])
        self.assertEqual(members, {})
        self.assertEqual(frames, {})
        self.assertIsNotNone(artifact)

    def test_detached_index_hash_and_member_tamper_are_rejected(self):
        for field in ("sha256", "members"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index = json.loads(
                    (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_text()
                )
                artifact = index["artifacts"][0]
                artifact[field] = "0" * 64 if field == "sha256" else ["forged"]
                index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
                index_path.parent.mkdir(parents=True)
                index_path.write_text(json.dumps(index))
                run = self.current_manifest()["runs"]["diagnostic_10_min"]
                errors: list[str] = []
                validator.validate_package(
                    root,
                    run["package"],
                    validator.DIAGNOSTIC_MEMBERS,
                    "diagnostic run",
                    errors,
                )
            self.assertTrue(any(field in error for error in errors), errors)

    def test_cannot_claim_qualification_or_open_p4e(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["qualification_status"] = "PASS"
            manifest["p4e_gate"] = "OPEN"
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("P3B qualification must remain PARTIAL", errors)
        self.assertIn("P4E gate must remain BLOCKED", errors)

    def test_analyzer_export_cannot_be_claimed_without_archived_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["operator_configuration_attestation"][
                "independent_analyzer_export"
            ] = "analyzer.csv"
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("operator configuration attestation mismatch", errors)

    def test_tampered_detached_package_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_bytes(
                (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_bytes()
            )
            run = self.current_manifest()["runs"]["diagnostic_10_min"]
            run["package"]["sha256"] = "0" * 64
            errors: list[str] = []
            validator.validate_package(
                root,
                run["package"],
                validator.DIAGNOSTIC_MEMBERS,
                "diagnostic run",
                errors,
            )
        self.assertTrue(
            any(error.startswith("detached package sha256 mismatch:") for error in errors),
            errors,
        )

    def test_frames_hash_is_bound_between_status_and_package(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["runs"]["frozen_30_min_qualified"]["frames_csv"]["sha256"] = (
                "0" * 64
            )
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertTrue(
            any(
                error
                in {
                    "qualified frozen long run frames metadata mismatch between package and status",
                    "qualified frozen long run detached key excerpt mismatch",
                }
                for error in errors
            ),
            errors,
        )

    def test_paired_frames_metadata_tamper_is_rejected_by_immutable_hash(self):
        run = self.current_manifest()["runs"]["diagnostic_10_min"]
        run["frames_csv"]["sha256"] = "0" * 64
        index = json.loads(
            (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_text()
        )
        artifact = index["artifacts"][0]
        artifact["key_excerpt"]["frames_csv_sha256"] = "0" * 64
        errors: list[str] = []
        validator.validate_detached_run(
            run,
            artifact,
            "FAIL_FIXED_WINDOW_THROUGHPUT",
            "diagnostic",
            "diagnostic run",
            errors,
        )
        self.assertIn("diagnostic run immutable source hash mismatch: frames.csv", errors)

    def test_reader_visible_statement_cannot_claim_p3b_pass_or_open_p4e(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["evidence_boundary"]["statement"] = (
                "P3B passed completely and P4E is open."
            )
            errors = validator.validate(
                ROOT, self.write_manifest(directory, manifest)
            )
        self.assertIn("load evidence statement mismatch", errors)

    def test_qualified_run_must_retain_host_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["runs"]["frozen_30_min_qualified"]["acceptance_observed"][
                "host_acceptance"
            ] = False
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertTrue(
            any(
                error
                in {
                    "qualified frozen long run observed acceptance mismatch",
                    "qualified frozen long run detached host acceptance mismatch",
                }
                for error in errors
            ),
            errors,
        )

    def test_analyzer_limitation_must_remain_explicit(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["evidence_boundary"]["limitations"] = []
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn(
            "load evidence must record the 6000 frame/s analyzer limitation",
            errors,
        )

    def test_completed_backpressure_cannot_be_returned_to_pending(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["evidence_boundary"]["pending"].append(
                "USB backpressure under CAN load"
            )
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn("load evidence pending set mismatch", errors)

    def test_completed_analyzer_reconciliation_cannot_be_returned_to_pending(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            manifest["evidence_boundary"]["pending"].insert(
                0,
                "independent analyzer timestamp and bit-timing reconciliation at <=1000 frame/s",
            )
            errors = validator.validate(
                ROOT, self.write_manifest(directory, manifest)
            )
        self.assertIn("load evidence pending set mismatch", errors)

    def test_nested_analyzer_evidence_cannot_claim_high_rate_coverage(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_ref = manifest["supplemental_evidence"][
                "independent_analyzer_low_rate"
            ]
            analyzer = json.loads((ROOT / source_ref["path"]).read_text())
            analyzer["outcomes"]["high_rate_analyzer_timestamp_coverage"] = "PASS"
            analyzer_path = directory / "analyzer.json"
            analyzer_path.write_text(
                json.dumps(analyzer, indent=2, sort_keys=True) + "\n"
            )
            source_ref["path"] = analyzer_path.relative_to(ROOT).as_posix()
            source_ref["sha256"] = hashlib.sha256(
                analyzer_path.read_bytes()
            ).hexdigest()
            errors = validator.validate(
                ROOT, self.write_manifest(directory, manifest)
            )
        self.assertIn(
            "low-rate analyzer evidence: analyzer evidence outcomes mismatch",
            errors,
        )

    def test_hotplug_scope_cannot_claim_100_cycles(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_ref = manifest["supplemental_evidence"]["physical_usb_hotplug"]
            hotplug = json.loads((ROOT / source_ref["path"]).read_text())
            hotplug["evidence_boundary"]["covered"] = (
                "100 physical disconnect/reconnect cycles"
            )
            hotplug_path = directory / "hotplug.json"
            hotplug_path.write_text(json.dumps(hotplug, indent=2, sort_keys=True) + "\n")
            source_ref["path"] = hotplug_path.relative_to(ROOT).as_posix()
            source_ref["sha256"] = hashlib.sha256(hotplug_path.read_bytes()).hexdigest()
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn(
            "physical USB hotplug evidence retains stale 100-cycle scope",
            errors,
        )

    def test_bus_off_readiness_cannot_be_upgraded_to_actual_hil_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_ref = manifest["supplemental_evidence"][
                "bus_off_fault_injection_readiness"
            ]
            readiness = json.loads((ROOT / source_ref["path"]).read_text())
            readiness["actual_hil"]["executed"] = True
            readiness["actual_hil"]["outcome"] = "PASS"
            readiness["actual_hil"]["status"] = "PASS"
            readiness_path = directory / "readiness.json"
            readiness_path.write_text(
                json.dumps(readiness, indent=2, sort_keys=True) + "\n"
            )
            source_ref["path"] = readiness_path.relative_to(ROOT).as_posix()
            source_ref["sha256"] = hashlib.sha256(
                readiness_path.read_bytes()
            ).hexdigest()
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn(
            "bus-off readiness evidence: actual bus-off HIL attempt evidence mismatch",
            errors,
        )

    def test_historical_bus_off_blocker_remains_bound(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            manifest = self.current_manifest()
            source_ref = manifest["supplemental_evidence"][
                "historical_bus_off_fault_injection_blocker"
            ]
            source_ref["sha256"] = "0" * 64
            errors = validator.validate(ROOT, self.write_manifest(directory, manifest))
        self.assertIn(
            "historical bus-off blocker evidence SHA-256 mismatch", errors
        )


if __name__ == "__main__":
    unittest.main()
