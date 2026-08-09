import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/validate_phase1b_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_phase1b_contract", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class Phase1BContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in ("docs", ".github", ".vscode", "tests"):
            shutil.copytree(ROOT / relative, self.root / relative)

    def tearDown(self):
        self.temp.cleanup()

    def test_repository_phase1b_contract_passes(self):
        self.assertEqual(VALIDATOR.validate(ROOT), [])

    def test_required_gate_regression_reopens_phase(self):
        path = self.root / "docs/evidence/phase1/phase1b-closure.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["required_gates"]["jlink_debug_adapter"]["status"] = "PARTIAL"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        errors = VALIDATOR.validate(self.root)
        self.assertTrue(any("required Phase 1B gate is not PASS" in item for item in errors))

    def test_missing_evidence_reopens_phase(self):
        (self.root / "docs/evidence/phase1/T-DEV-005-jlink-gdb-report.md").unlink()
        errors = VALIDATOR.validate(self.root)
        self.assertTrue(any("cannot read" in item for item in errors))

    def test_stale_blocker_reopens_phase(self):
        path = self.root / "docs/development/adr-host-stack-spike.md"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\nFormal host codec work remains prohibited until later.\n",
            encoding="utf-8",
        )
        errors = VALIDATOR.validate(self.root)
        self.assertTrue(any("stale Phase 1B blocker" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
