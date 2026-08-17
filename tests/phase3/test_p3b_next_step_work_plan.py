from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = Path("docs/development/p3b-next-step-work-plan.md")
STATUS = Path("docs/evidence/phase3/P3B-current-status.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_next_step_work_plan.py"
    spec = importlib.util.spec_from_file_location("p3b_next_step_work_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bNextStepWorkPlanTests(unittest.TestCase):
    def validate_plan(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "plan.md"
            path.write_text(text, encoding="utf-8")
            return validator.validate(ROOT, path.relative_to(ROOT), STATUS)

    def validate_status(self, value: dict) -> list[str]:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return validator.validate(ROOT, PLAN, path.relative_to(ROOT))

    def test_repository_plan_passes(self):
        self.assertEqual(validator.validate(ROOT, PLAN, STATUS), [])

    def test_plan_cannot_claim_qualification_or_hardware_authorization(self):
        text = (ROOT / PLAN).read_text(encoding="utf-8")
        text += "\nP4E=PASS\nhardware_execution_authorized=true\n"
        errors = self.validate_plan(text)
        self.assertIn(
            "next-step plan contains forbidden qualification claim: P4E=PASS",
            errors,
        )
        self.assertIn(
            "next-step plan contains forbidden qualification claim: "
            "hardware_execution_authorized=true",
            errors,
        )

    def test_plan_requires_deferral_contract_marker(self):
        text = (ROOT / PLAN).read_text(encoding="utf-8")
        text = text.replace("hardware_bus_off=NOT_COMPLETED", "")
        self.assertIn(
            "next-step plan requires exactly one marker: "
            "hardware_bus_off=NOT_COMPLETED",
            self.validate_plan(text),
        )

    def test_plan_sequences_single_channel_before_dual_channel(self):
        text = (ROOT / PLAN).read_text(encoding="utf-8")
        wp2 = text.index("## 5. WP2")
        wp3 = text.index("## 6. WP3")
        wp5 = text.index("## 8. WP5")
        deferred = text.index("## 9. Deferred lane")
        reordered = (
            text[:wp2]
            + text[wp5:deferred]
            + text[wp3:wp5]
            + text[wp2:wp3]
            + text[deferred:]
        )
        errors = self.validate_plan(reordered)
        self.assertIn("next-step plan work-package order mismatch", errors)
        self.assertIn(
            "next-step plan must sequence single-channel before dual-channel", errors
        )

    def test_authoritative_status_cannot_be_upgraded(self):
        value = json.loads((ROOT / STATUS).read_text(encoding="utf-8"))
        value["qualification_status"] = "PASS"
        value["p4e_gate"] = "OPEN"
        errors = self.validate_status(value)
        self.assertIn(
            "next-step plan status mismatch: qualification_status", errors
        )
        self.assertIn("next-step plan status mismatch: p4e_gate", errors)


if __name__ == "__main__":
    unittest.main()
