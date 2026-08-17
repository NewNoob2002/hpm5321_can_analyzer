from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFERRAL = Path(
    "docs/evidence/phase3/P3B-bus-off-deferral-2026-08-17.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_bus_off_deferral.py"
    spec = importlib.util.spec_from_file_location("p3b_bus_off_deferral", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bBusOffDeferralTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads((ROOT / DEFERRAL).read_text())

    def validate_value(self, value):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "deferral.json"
            path.write_text(json.dumps(value))
            return validator.validate(ROOT, path.relative_to(ROOT))

    def test_repository_deferral_passes(self):
        self.assertEqual(validator.validate(ROOT, DEFERRAL), [])

    def test_deferral_cannot_claim_bus_off_pass(self):
        value = copy.deepcopy(self.value)
        value["hardware_bus_off_status"] = "PASS"
        self.assertIn(
            "P3B deferral mismatch: hardware_bus_off_status",
            self.validate_value(value),
        )

    def test_deferral_cannot_open_qualification_or_freeze(self):
        value = copy.deepcopy(self.value)
        value["p4e_qualification_gate"] = "OPEN"
        value["freeze_ready"] = True
        errors = self.validate_value(value)
        self.assertIn("P3B deferral mismatch: p4e_qualification_gate", errors)
        self.assertIn("P3B deferral mismatch: freeze_ready", errors)

    def test_deferral_cannot_authorize_hardware_execution(self):
        value = copy.deepcopy(self.value)
        value["hardware_execution_authorized"] = True
        self.assertIn(
            "P3B deferral mismatch: hardware_execution_authorized",
            self.validate_value(value),
        )

    def test_deferral_cannot_remove_resume_condition(self):
        value = copy.deepcopy(self.value)
        value["resume_conditions"].pop()
        self.assertIn(
            "P3B deferral policy mismatch: resume_conditions",
            self.validate_value(value),
        )

    def test_deferral_reference_hash_is_immutable(self):
        value = copy.deepcopy(self.value)
        value["authoritative_references"]["last_attempt"]["sha256"] = "0" * 64
        self.assertIn(
            "P3B deferral reference SHA-256 mismatch: last_attempt",
            self.validate_value(value),
        )


if __name__ == "__main__":
    unittest.main()
