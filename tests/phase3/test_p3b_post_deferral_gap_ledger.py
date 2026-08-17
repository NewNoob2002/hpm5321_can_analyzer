from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path("docs/development/p3b-post-deferral-gap-ledger.json")
OWNERSHIP = Path("docs/development/p3b-post-deferral-file-ownership.json")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_post_deferral_gap_ledger.py"
    spec = importlib.util.spec_from_file_location("p3b_post_deferral_gap_ledger", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bPostDeferralGapLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads((ROOT / LEDGER).read_text(encoding="utf-8"))
        self.ownership = json.loads((ROOT / OWNERSHIP).read_text(encoding="utf-8"))

    def validate_values(self, ledger=None, ownership=None):
        ledger = copy.deepcopy(self.ledger if ledger is None else ledger)
        ownership = copy.deepcopy(self.ownership if ownership is None else ownership)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            ledger_path = root / "ledger.json"
            ownership_path = root / "ownership.json"
            ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
            ownership_path.write_text(json.dumps(ownership, sort_keys=True), encoding="utf-8")
            return validator.validate(ROOT, ledger_path.relative_to(ROOT), ownership_path.relative_to(ROOT))

    def entry(self, test_id):
        return next(item for item in self.ledger["entries"] if item["test_id"] == test_id)

    def test_repository_contract_passes(self):
        self.assertEqual(validator.validate(ROOT, LEDGER, OWNERSHIP), [])

    def test_required_test_id_missing_fails(self):
        self.ledger["entries"] = [item for item in self.ledger["entries"] if item["test_id"] != "T-PROTO-001"]
        self.assertTrue(any("missing required test IDs: T-PROTO-001" in error for error in self.validate_values()))

    def test_duplicate_test_id_fails(self):
        self.ledger["entries"].append(copy.deepcopy(self.ledger["entries"][0]))
        self.assertTrue(any("duplicate test ID" in error for error in self.validate_values()))

    def test_missing_owner_fails(self):
        self.entry("T-PROTO-001")["owner_role"] = ""
        self.assertIn("T-PROTO-001 missing owner_role", self.validate_values())

    def test_missing_next_action_fails(self):
        self.entry("T-PROTO-001")["next_action"] = ""
        self.assertIn("T-PROTO-001 missing next_action", self.validate_values())

    def test_invalid_traceability_fields_fail(self):
        cases = (
            ("requirement_ids", [], "invalid or empty requirement_ids"),
            ("requirement_ids", "REQ-P4P-001", "invalid or empty requirement_ids"),
            ("requirement_ids", [""], "invalid or empty requirement_ids"),
            ("requirement_ids", ["   "], "invalid or empty requirement_ids"),
            ("blockers", [], "invalid or empty blockers"),
            ("blockers", "NONE", "invalid or empty blockers"),
            ("blockers", [""], "invalid or empty blockers"),
            ("blockers", ["   "], "invalid or empty blockers"),
            (
                "artifact_identity",
                [],
                "artifact_identity must be a non-empty array",
            ),
            (
                "artifact_identity",
                "not-an-array",
                "artifact_identity must be a non-empty array",
            ),
            (
                "artifact_identity",
                {},
                "artifact_identity must be a non-empty array",
            ),
        )
        for field, invalid_value, diagnostic in cases:
            with self.subTest(field=field, invalid_value=invalid_value):
                ledger = copy.deepcopy(self.ledger)
                item = next(
                    entry
                    for entry in ledger["entries"]
                    if entry["test_id"] == "T-PROTO-001"
                )
                item[field] = invalid_value
                self.assertIn(
                    f"T-PROTO-001 {diagnostic}",
                    self.validate_values(ledger=ledger),
                )

        artifact_cases = (
            (["not-an-object"], "artifact_identity[0] must be an object"),
            ([{}], "artifact_identity[0] has invalid status"),
            (
                [
                    {
                        "status": "BOUND",
                        "kind": "REPOSITORY_GIT_BLOB",
                        "role": "",
                        "path": "",
                        "commit": validator.BASE_SHA,
                        "blob": "",
                    }
                ],
                "artifact_identity[0] has invalid or empty role",
            ),
            (
                [
                    {
                        "status": "NOT_PRODUCED",
                        "kind": "QUALIFICATION_CLOSURE_ARTIFACT",
                        "reason": "",
                        "expected_owner": "B1_PROTOCOL_HOST_CORE_OWNER",
                    }
                ],
                "artifact_identity[0] missing reason",
            ),
            (
                [
                    {
                        "status": "NOT_EXECUTED",
                        "kind": "QUALIFICATION_CLOSURE_ARTIFACT",
                        "reason": "Not run.",
                        "expected_owner": "",
                    }
                ],
                "artifact_identity[0] expected_owner mismatch",
            ),
        )
        for invalid_value, diagnostic in artifact_cases:
            with self.subTest(artifact_identity=invalid_value):
                ledger = copy.deepcopy(self.ledger)
                item = next(
                    entry
                    for entry in ledger["entries"]
                    if entry["test_id"] == "T-PROTO-001"
                )
                item["artifact_identity"] = invalid_value
                self.assertIn(
                    f"T-PROTO-001 {diagnostic}",
                    self.validate_values(ledger=ledger),
                )

    def test_pass_without_evidence_or_source_identity_fails(self):
        item = self.entry("T-PROTO-001")
        item["conservative_status"] = "PASS"
        item["evidence_paths"] = []
        item["evidence_source_identity"] = []
        errors = self.validate_values()
        self.assertTrue(any("requires evidence_paths" in error for error in errors))
        self.assertTrue(any("PASS requires evidence and source identity" in error for error in errors))

    def test_qualification_upgrade_fails(self):
        self.entry("T-PROTO-001")["qualification_status"] = "PASS"
        self.assertTrue(any("qualification status upgrade" in error for error in self.validate_values()))

    def test_hardware_upgrade_fails(self):
        self.entry("T-E2E-001")["hardware_evidence_status"] = "PASS"
        self.assertTrue(any("hardware evidence status upgrade" in error for error in self.validate_values()))

    def test_governance_upgrade_fails(self):
        self.ledger["governance_invariants"]["P3B"] = "PASS"
        self.ledger["governance_invariants"]["hardware_execution_authorized"] = True
        errors = self.validate_values()
        self.assertIn("governance invariant mismatch: P3B", errors)
        self.assertIn("governance invariant mismatch: hardware_execution_authorized", errors)

    def test_e2e009_cannot_be_closed_by_software(self):
        item = self.entry("T-E2E-009")
        item["conservative_status"] = "PASS"
        item["hardware_evidence_status"] = "NOT_APPLICABLE"
        self.assertIn("T-E2E-009 cannot be closed by software or split evidence", self.validate_values())

    def test_fw003_must_remain_deferred(self):
        item = self.entry("T-FW-003")
        item["implementation_status"] = "IMPLEMENTED"
        item["owner_role"] = "E1_DUAL_CHANNEL_OWNER"
        self.assertIn("T-FW-003 must remain in the deferred lane", self.validate_values())

    def test_dual_channel_before_single_channel_fails(self):
        self.ownership["work_order"] = ["WP0", "WP1", "WP5", "WP2", "WP3||WP4"]
        self.assertIn("work-package order must preserve single-channel before dual-channel", self.validate_values())

    def test_wp5_without_wp3_safety_dependency_fails(self):
        self.ownership["waves"][4]["start_gate"] = "WP2_ACCEPTED"
        self.assertIn("WP5 must depend on WP2 and relevant WP3 safety controls", self.validate_values())

    def test_protocol_hotspot_multiple_writer_fails(self):
        self.ownership["waves"][1]["writers"]["B2_PROTOCOL_INDEPENDENT_REVIEWER"] = ["protocol/v1/**"]
        self.assertTrue(any("multiple writers in wave 1 for protocol/v1/**" in error for error in self.validate_values()))

    def test_protocol_hotspot_broad_read_only_writer_fails(self):
        self.ownership["waves"][1]["writers"]["B2_PROTOCOL_INDEPENDENT_REVIEWER"] = [
            "host/crates/core/**"
        ]
        errors = self.validate_values()
        self.assertIn("wave 1 writers do not match authorized manifest", errors)
        self.assertIn(
            "wave 1 read-only role cannot be a writer: B2_PROTOCOL_INDEPENDENT_REVIEWER",
            errors,
        )

    def test_c2_protocol_hotspot_fails(self):
        hotspot = next(item for item in self.ownership["exclusive_hotspots"] if item["hotspot_id"] == "C2_APPLICATION_LAYER_ONLY")
        hotspot["patterns"].append("host/crates/core/src/lib.rs")
        self.assertIn("C2 cannot own protocol, Host Core, or firmware hotspots", self.validate_values())

    def test_d1_c1_hotspot_without_reauthorization_fails(self):
        self.ownership["waves"][3]["writers"]["D1_FIRMWARE_RELIABILITY_OWNER"].append("USER/src/app_mcan0_owner.c")
        self.assertIn("D1 cannot own C1 hotspots without reauthorization", self.validate_values())

    def test_m1_hardware_authority_fails(self):
        self.ownership["deferred_lane"]["hardware_execution_authorized"] = True
        self.ownership["deferred_lane"]["hardware_commands"] = ["inject bus-off"]
        self.assertIn("M1 cannot receive hardware execution authority or commands", self.validate_values())

    def test_source_identity_blob_mismatch_fails(self):
        self.entry("T-PROTO-001")["evidence_source_identity"][0]["blob"] = "0" * 40
        errors = self.validate_values()
        self.assertTrue(
            any("source identity[0] baseline blob mismatch" in error for error in errors)
        )
        self.assertTrue(
            any("source identity[0] working tree blob mismatch" in error for error in errors)
        )

    def test_source_identity_must_exist_at_baseline(self):
        item = self.entry("T-PROTO-001")
        path = OWNERSHIP.as_posix()
        item["evidence_paths"] = [path]
        item["evidence_source_identity"] = [
            {
                "type": "git_blob",
                "commit": validator.BASE_SHA,
                "path": path,
                "blob": validator.git_blob(ROOT / OWNERSHIP),
            }
        ]
        self.assertTrue(
            any(
                "source identity[0] is not present at baseline commit" in error
                for error in self.validate_values()
            )
        )

    def test_top_level_source_identity_mismatch_fails(self):
        self.ledger["planning_contract"]["blob"] = "0" * 40
        self.ledger["authoritative_status"]["blob"] = "0" * 40
        errors = self.validate_values()
        self.assertIn("planning contract baseline blob mismatch", errors)
        self.assertIn("authoritative status baseline blob mismatch", errors)

    def test_evidence_path_escape_fails(self):
        item = self.entry("T-PROTO-001")
        item["evidence_paths"][0] = "../outside.json"
        item["evidence_source_identity"][0]["path"] = "../outside.json"
        self.assertTrue(
            any(
                "invalid T-PROTO-001 source identity[0]" in error
                for error in self.validate_values()
            )
        )

    def test_historical_blocker_authority_redefinition_fails(self):
        self.ledger["authoritative_status"]["historical_blocker"]["authority"] = "CURRENT"
        self.ownership["preserved_authorities"][0]["sha256"] = "0" * 64
        errors = self.validate_values()
        self.assertIn("historical blocker authority was redefined", errors)
        self.assertIn("historical blocker authority was redefined in ownership manifest", errors)


if __name__ == "__main__":
    unittest.main()
