from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(
    "docs/evidence/phase3/P3B-HIL-backpressure-evidence-2026-08-15.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_backpressure_evidence.py"
    spec = importlib.util.spec_from_file_location("p3b_backpressure_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bBackpressureEvidenceTests(unittest.TestCase):
    def current_evidence(self) -> dict:
        return json.loads((ROOT / EVIDENCE).read_text())

    def write_evidence(self, directory: Path, value: dict) -> Path:
        path = directory / "evidence.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def test_current_evidence_passes(self):
        self.assertEqual(validator.validate(ROOT, EVIDENCE), [])

    def test_missing_large_zip_validates_repository_key_excerpt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_path = root / EVIDENCE
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_bytes((ROOT / EVIDENCE).read_bytes())
            index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
            index_path.write_bytes(
                (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_bytes()
            )
            errors = validator.validate(root, EVIDENCE)
        self.assertEqual(errors, [])

    def test_missing_large_zip_rejects_detached_excerpt_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_path = root / EVIDENCE
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_bytes((ROOT / EVIDENCE).read_bytes())
            index = json.loads(
                (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_text()
            )
            index["artifacts"][3]["key_excerpt"]["frames"] += 1
            index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
            index_path.write_text(json.dumps(index))
            errors = validator.validate(root, EVIDENCE)
        self.assertIn("backpressure detached key excerpt mismatch", errors)

    def test_channel_attribution_cannot_be_claimed_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            evidence["status"] = "PASS"
            evidence["outcomes"]["channel_sequence_reconciliation"] = "PASS"
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn("backpressure evidence must remain PARTIAL", errors)
        self.assertIn("backpressure evidence outcomes mismatch", errors)

    def test_tampered_package_hash_is_rejected_by_detached_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.current_evidence()
            evidence["package"]["sha256"] = "0" * 64
            evidence_path = root / EVIDENCE
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n"
            )
            index_path = root / "docs/evidence/phase3/P3B-external-artifacts.json"
            index_path.write_bytes(
                (ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_bytes()
            )
            errors = validator.validate(root, EVIDENCE)
        self.assertTrue(
            any(error.startswith("detached package sha256 mismatch:") for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
