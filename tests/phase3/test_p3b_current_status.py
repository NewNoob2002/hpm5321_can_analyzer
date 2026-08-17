from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATUS = Path("docs/evidence/phase3/P3B-current-status.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_current_status.py"
    spec = importlib.util.spec_from_file_location("p3b_current_status", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bCurrentStatusTests(unittest.TestCase):
    def test_repository_status_passes(self):
        self.assertEqual(validator.validate(ROOT, STATUS), [])

    def test_status_cannot_claim_bus_off_pass(self):
        value = json.loads((ROOT / STATUS).read_text())
        value["bus_off_gate"] = "PASS"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value))
            errors = validator.validate(ROOT, path.relative_to(ROOT))
        self.assertIn("P3B current status mismatch: bus_off_gate", errors)

    def test_historical_blocker_cannot_become_authoritative(self):
        value = json.loads((ROOT / STATUS).read_text())
        value["historical_blocker"]["authority"] = "AUTHORITATIVE"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value))
            errors = validator.validate(ROOT, path.relative_to(ROOT))
        self.assertIn("historical blocker must remain preserved and non-authoritative", errors)

    def test_development_continuation_cannot_open_p4e(self):
        value = json.loads((ROOT / STATUS).read_text())
        value["p4e_gate"] = "OPEN"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value))
            errors = validator.validate(ROOT, path.relative_to(ROOT))
        self.assertIn("P3B current status mismatch: p4e_gate", errors)

    def test_development_continuation_value_is_fixed(self):
        value = json.loads((ROOT / STATUS).read_text())
        value["development_continuation"] = "QUALIFICATION_COMPLETE"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value))
            errors = validator.validate(ROOT, path.relative_to(ROOT))
        self.assertIn(
            "P3B current status mismatch: development_continuation", errors
        )

    def test_deferral_reference_is_required_and_hash_bound(self):
        value = json.loads((ROOT / STATUS).read_text())
        value["authoritative_evidence"]["bus_off_deferral"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value))
            errors = validator.validate(ROOT, path.relative_to(ROOT))
        self.assertIn(
            "authoritative evidence SHA-256 mismatch: bus_off_deferral", errors
        )

    def test_pending_external_locations_keep_freeze_blocked(self):
        self.assertFalse(json.loads((ROOT / STATUS).read_text())["freeze_status"] == "READY")
        index = json.loads((ROOT / "docs/evidence/phase3/P3B-external-artifacts.json").read_text())
        self.assertFalse(index["freeze_ready"])
        self.assertTrue(all(item["archive_status"] == "PENDING_UPLOAD" for item in index["artifacts"]))


if __name__ == "__main__":
    unittest.main()
