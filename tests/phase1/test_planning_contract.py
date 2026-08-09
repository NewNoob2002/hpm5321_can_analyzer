import importlib.util
import shutil
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/validate_planning_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_planning_contract", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class PlanningContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "docs", self.root / "docs")
        shutil.copytree(ROOT / "boards", self.root / "boards")

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, relative: str, old: str, new: str):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def assert_error(self, fragment: str, frozen: bool = False):
        errors = VALIDATOR.validate(self.root, require_storage_frozen=frozen)
        self.assertTrue(any(fragment in item for item in errors), errors)

    def mutate_all(self, relative: str, old: str, new: str):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_repository_contract_is_structurally_valid(self):
        self.assertEqual(VALIDATOR.validate(ROOT), [])

    def test_pin_map_mismatch_fails(self):
        self.mutate(
            "docs/hardware/phase0-hardware-manifest.md",
            "| SPI2 SCLK | PB11 |",
            "| SPI2 SCLK | PB14 |",
        )
        self.assert_error("pin map mismatch")

    def test_board_source_mismatch_fails(self):
        self.mutate(
            "boards/hpm5321_custom/pinmux.c",
            "IOC_PB11_FUNC_CTL_SPI2_SCLK",
            "IOC_PB11_FUNC_CTL_GPIO_B_11",
        )
        self.assert_error("source token missing")

    def test_channel_alias_mismatch_fails(self):
        self.mutate(
            "docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md",
            "CAN2 = MCAN2",
            "CAN2 = MCAN1",
        )
        self.assert_error("channel alias")

    def test_led_gate_mismatch_fails(self):
        self.mutate(
            "docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md",
            "| T-LED-003 | D | P0 required(MVP+) |",
            "| T-LED-003 | B | P0 required(MVP+) |",
        )
        self.assert_error("LED test registry mismatch")

    def test_release_chain_mismatch_fails(self):
        self.mutate_all(
            "docs/approved-plan/prd-hpm5321-usb-can-analyzer.md",
            "P0S -> P3C1 -> P3C2 -> P5S",
            "P0S -> P3C2 -> P5S",
        )
        self.assert_error("release chain mismatch")

    def test_profile_tbd_fails(self):
        self.mutate(
            "docs/approved-plan/profiles/bp-storage-v1.md",
            "BLOCKED(P0S)",
            "TBD",
        )
        self.assert_error("profile contains TBD")

    def test_unfrozen_profile_fails_execution_gate(self):
        self.assert_error("storage profile is not FROZEN", frozen=True)

    def test_approval_order_fails(self):
        self.mutate(
            "docs/approved-plan/critic-approval.md",
            "- Sequence: 2\n",
            "- Sequence: 1\n",
        )
        self.assert_error("approval section mismatch")

    def test_incomplete_handoff_fails(self):
        self.mutate(
            "docs/approved-plan/consensus-handoff.md",
            "    complete: true\n    execution_authorized: true",
            "    complete: false\n    execution_authorized: true",
        )
        self.assert_error("handoff entry")


if __name__ == "__main__":
    unittest.main()
