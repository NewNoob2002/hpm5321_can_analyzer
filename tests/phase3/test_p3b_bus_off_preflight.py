from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = Path(
    "docs/evidence/phase3/P3B-active-bus-off-hil-preflight.template.json"
)
CURRENT_PREFLIGHT = Path(
    "docs/evidence/phase3/P3B-active-bus-off-hil-preflight-2026-08-17.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_bus_off_preflight.py"
    spec = importlib.util.spec_from_file_location("p3b_bus_off_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bBusOffPreflightTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((ROOT / PREFLIGHT).read_text())
        self.current = json.loads((ROOT / CURRENT_PREFLIGHT).read_text())

    def validate_value(self, value):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "preflight.json"
            path.write_text(json.dumps(value))
            return validator.validate(ROOT, path.relative_to(ROOT))

    def ready_fixture(self):
        # These recorded-* values are test-only fixtures, not asserted field data.
        value = copy.deepcopy(self.template)
        value["bench"] = {
            "isolated_bench_confirmed": True,
            "vehicle_connected": False,
            "production_gateway_connected": False,
            "emergency_stop_or_power_cut_method": "recorded-power-cut",
        }
        value["dut"] = {
            "model": "recorded-dut-model",
            "hardware_revision": "recorded-hw-revision",
            "serial_number": "recorded-dut-serial",
            "target_voltage_v": 5.0,
        }
        value["debug_probe"] = {
            "model": "recorded-probe-model",
            "serial_number": "recorded-probe-serial",
            "firmware_version": "recorded-probe-firmware",
        }
        value["can_analyzer"] = {
            "model": "recorded-analyzer-model",
            "serial_number": "recorded-analyzer-serial",
            "firmware_or_software_version": "recorded-analyzer-version",
            "mode": "recorded-analyzer-mode",
            "timestamp_resolution": "recorded-resolution",
        }
        value["active_fault_injector"] = {
            "present": True,
            "model": "recorded-injector-model",
            "serial_number": "recorded-injector-serial",
            "firmware_or_software_version": "recorded-injector-version",
            "supported_injection_types": ["recorded-injection-type"],
            "selected_injection_type": "recorded-injection-type",
            "operating_limits": "recorded-approved-limits",
            "emergency_stop_condition": "recorded-stop-condition",
        }
        value["bus"] = {
            "bitrate_bits_per_second": 1_000_000,
            "sample_point_percent": 80.0,
            "fd_enabled": False,
            "termination_ohms": 60.0,
            "common_ground_confirmed": True,
            "measured_idle_voltage": "recorded-measurement",
        }
        value["execution"]["post_latch_observation_seconds"] = 60
        value["execution"]["raw_gdb_capture_available"] = True
        value["execution"]["raw_analyzer_capture_available"] = True
        for index, run in enumerate(value["runs"], start=1):
            run["run_id"] = f"recorded-run-{index}"
            run["nonce"] = index
            run["log_directory"] = f"recorded/log-{index}"
            run["gdb_transcript"] = f"recorded/gdb-{index}.txt"
            run["analyzer_raw_file"] = f"recorded/analyzer-{index}.raw"
            run["wiring_record"] = f"recorded/wiring-{index}.json"
            run["equipment_identity_record"] = f"recorded/equipment-{index}.json"
        value["operator"] = {"identity": "recorded-operator", "approval": True}
        value["independent_reviewer"] = {
            "identity": "recorded-reviewer",
            "approval": True,
            "distinct_from_operator": True,
        }
        value["project_safety_approver"] = {
            "identity": "recorded-safety-approver",
            "approval": True,
            "scope": "recorded-approved-scope",
        }
        value["decision"] = "READY_FOR_HIL_PREFLIGHT_APPROVAL"
        value["approved"] = True
        value["blockers"] = []
        return value

    def test_repository_template_is_valid_and_blocked(self):
        self.assertEqual(validator.validate(ROOT, PREFLIGHT), [])
        self.assertEqual(
            self.template["blockers"], validator.readiness_blockers(self.template)
        )
        self.assertEqual(len(self.template["blockers"]), 11)
        self.assertFalse(self.template["hardware_execution_authorized"])

    def test_current_record_is_valid_and_blocked_only_on_unresolved_inputs(self):
        self.assertEqual(validator.validate(ROOT, CURRENT_PREFLIGHT), [])
        self.assertEqual(
            self.current["blockers"], validator.readiness_blockers(self.current)
        )
        self.assertEqual(len(self.current["blockers"]), 4)
        self.assertFalse(self.current["approved"])
        self.assertFalse(self.current["hardware_execution_authorized"])

    def test_missing_inputs_cannot_claim_ready_or_approval(self):
        value = copy.deepcopy(self.template)
        value["decision"] = "READY_FOR_HIL_PREFLIGHT_APPROVAL"
        value["approved"] = True
        errors = self.validate_value(value)
        self.assertIn("preflight decision does not match blockers", errors)
        self.assertIn("preflight approval does not match blockers", errors)

    def test_software_identity_hash_cannot_change(self):
        value = copy.deepcopy(self.template)
        value["software_identity"]["debug_elf_sha256"] = "0" * 64
        errors = self.validate_value(value)
        self.assertIn("preflight software identity mismatch", errors)

    def test_complete_fixture_can_reach_preflight_approval_only(self):
        value = self.ready_fixture()
        self.assertEqual(validator.readiness_blockers(value), [])
        self.assertEqual(self.validate_value(value), [])
        self.assertFalse(value["hardware_execution_authorized"])

    def test_run_nonces_and_evidence_paths_must_be_unique(self):
        value = self.ready_fixture()
        value["runs"][1]["nonce"] = value["runs"][0]["nonce"]
        value["runs"][2]["log_directory"] = value["runs"][0]["log_directory"]
        blockers = validator.readiness_blockers(value)
        self.assertIn(validator.BLOCK_RUNS, blockers)

    def test_hardware_execution_cannot_be_authorized(self):
        value = self.ready_fixture()
        value["hardware_execution_authorized"] = True
        errors = self.validate_value(value)
        self.assertIn(
            "preflight header mismatch: hardware_execution_authorized", errors
        )

    def test_gdb_memory_writes_cannot_be_reclassified_as_hardware_pass(self):
        value = copy.deepcopy(self.current)
        value["gdb_fault_injection_policy"][
            "write_result_state_or_latch_for_hardware_pass_allowed"
        ] = True
        errors = self.validate_value(value)
        self.assertIn("preflight GDB fault-injection policy mismatch", errors)


if __name__ == "__main__":
    unittest.main()
