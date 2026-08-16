from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(
    "docs/evidence/phase3/P3B-bus-off-fault-injection-readiness-2026-08-15.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_bus_off_evidence.py"
    spec = importlib.util.spec_from_file_location("p3b_bus_off_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bBusOffEvidenceTests(unittest.TestCase):
    def current_manifest(self) -> dict:
        return json.loads((ROOT / MANIFEST).read_text())

    def write_manifest(self, directory: Path, value: dict) -> Path:
        path = directory / "readiness.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def materialize_root(self, directory: Path) -> Path:
        paths = set(validator.EXPECTED_SOURCE_HASHES)
        paths.update(validator.EXPECTED_ASSET_PATHS.values())
        paths.add(
            "docs/evidence/phase3/"
            "P3B-bus-off-fault-injection-blocker-2026-08-15.json"
        )
        paths.add(MANIFEST.as_posix())
        for relative in paths:
            source = ROOT / relative
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return directory

    def test_current_readiness_passes(self):
        self.assertEqual(validator.validate(ROOT, MANIFEST), [])

    def test_immutable_source_and_asset_sets_are_frozen(self):
        self.assertTrue(validator.EXPECTED_SOURCE_HASHES)
        self.assertEqual(
            set(validator.EXPECTED_ASSET_HASHES),
            set(validator.EXPECTED_ASSET_PATHS),
        )
        self.assertTrue(all(validator.EXPECTED_ASSET_HASHES.values()))

    def test_actual_hil_attempt_cannot_be_falsely_claimed_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_manifest()
            evidence["actual_hil"] = {
                "executed": True,
                "outcome": "PASS",
                "raw_evidence": {
                    "path": (
                        "docs/evidence/phase3/"
                        "P3B-bus-off-attempt-2026-08-15.json"
                    ),
                    "sha256": validator.EXPECTED_ATTEMPT_SHA256,
                },
                "status": "PASS",
            }
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("actual bus-off HIL attempt evidence mismatch", errors)
        self.assertIn("actual bus-off HIL PASS cannot be claimed", errors)

    def test_gates_cannot_be_upgraded_by_readiness(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_manifest()
            evidence["qualification_status"] = "PASS"
            evidence["p4e_gate"] = "OPEN"
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("bus-off readiness mismatch: qualification_status", errors)
        self.assertIn("bus-off readiness mismatch: p4e_gate", errors)

    def test_source_path_and_hash_cannot_be_repointed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            replacement = directory / "owner.c"
            replacement.write_text("tampered\n")
            evidence = self.current_manifest()
            reference = evidence["source"]["files"][3]
            reference["path"] = replacement.relative_to(ROOT).as_posix()
            reference["sha256"] = hashlib.sha256(
                replacement.read_bytes()
            ).hexdigest()
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("bus-off immutable source set mismatch", errors)

    def test_manual_acceptance_must_remain_pending(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_manifest()
            evidence["manual_acceptance"]["final_psr_bo"]["status"] = "PASS"
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("manual bus-off acceptance mismatch: final_psr_bo", errors)
        self.assertIn(
            "manual bus-off acceptance cannot claim PASS before HIL", errors
        )

    def test_historical_blocker_is_retained_but_not_authoritative(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_manifest()
            evidence["historical_blocker"]["authority"] = "AUTHORITATIVE"
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("historical bus-off blocker reference mismatch", errors)

    def test_arm_command_must_remain_last(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            arm = directory / "arm.gdb"
            arm.write_text(
                (ROOT / "scripts/phase3/p3b_bus_off_arm.gdb").read_text()
                + "set var g_app_mcan0_bus_off_test_mailbox.reserved = 0\n"
            )
            evidence = self.current_manifest()
            reference = evidence["assets"]["arm_gdb"]
            reference["path"] = arm.relative_to(ROOT).as_posix()
            reference["sha256"] = hashlib.sha256(arm.read_bytes()).hexdigest()
            errors = validator.validate(
                ROOT, self.write_manifest(directory, evidence)
            )
        self.assertIn("bus-off readiness asset mismatch: arm_gdb", errors)

    def test_arm_cannot_clear_once_per_boot_even_with_updated_manifest_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.materialize_root(Path(temporary))
            arm = root / validator.EXPECTED_ASSET_PATHS["arm_gdb"]
            text = arm.read_text().replace(
                "# command 必须最后写入；本脚本不自动 continue。",
                (
                    "set var g_app_mcan0_bus_off_test_result."
                    "once_per_boot_consumed = 0\n"
                    "# command 必须最后写入；本脚本不自动 continue。"
                ),
            )
            arm.write_text(text)
            manifest = root / MANIFEST
            evidence = json.loads(manifest.read_text())
            evidence["assets"]["arm_gdb"]["sha256"] = hashlib.sha256(
                arm.read_bytes()
            ).hexdigest()
            manifest.write_text(json.dumps(evidence, indent=2) + "\n")
            errors = validator.validate(root, MANIFEST)
        self.assertIn("bus-off immutable asset mismatch: arm_gdb", errors)
        self.assertIn(
            "bus-off arm writes must match the fail-closed mailbox sequence",
            errors,
        )

    def test_snapshot_cannot_be_reduced_to_a_comment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.materialize_root(Path(temporary))
            snapshot = root / validator.EXPECTED_ASSET_PATHS["snapshot_gdb"]
            snapshot.write_text("# g_app_mcan0_bus_off_test_result\n")
            manifest = root / MANIFEST
            evidence = json.loads(manifest.read_text())
            evidence["assets"]["snapshot_gdb"]["sha256"] = hashlib.sha256(
                snapshot.read_bytes()
            ).hexdigest()
            manifest.write_text(json.dumps(evidence, indent=2) + "\n")
            errors = validator.validate(root, MANIFEST)
        self.assertIn("bus-off immutable asset mismatch: snapshot_gdb", errors)
        self.assertIn("bus-off snapshot is missing required commands", errors)

    def test_retrigger_verify_cannot_drop_once_per_boot_assertions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.materialize_root(Path(temporary))
            verify = root / validator.EXPECTED_ASSET_PATHS[
                "retrigger_verify_gdb"
            ]
            verify.write_text(
                verify.read_text().replace(
                    (
                        "if g_app_mcan0_bus_off_test_result."
                        "tx_submit_count != 1"
                    ),
                    (
                        "if g_app_mcan0_bus_off_test_result."
                        "tx_submit_count != 2"
                    ),
                )
            )
            manifest = root / MANIFEST
            evidence = json.loads(manifest.read_text())
            evidence["assets"]["retrigger_verify_gdb"]["sha256"] = (
                hashlib.sha256(verify.read_bytes()).hexdigest()
            )
            manifest.write_text(json.dumps(evidence, indent=2) + "\n")
            errors = validator.validate(root, MANIFEST)
        self.assertIn(
            "bus-off immutable asset mismatch: retrigger_verify_gdb",
            errors,
        )
        self.assertIn(
            (
                "bus-off retrigger verify script missing assertion: "
                "g_app_mcan0_bus_off_test_result.tx_submit_count != 1"
            ),
            errors,
        )

    def test_impossible_tec_256_threshold_is_rejected(self):
        self.assertEqual(validator.EXPECTED_ACCEPTANCE["max_tec_minimum"], 128)
        self.assertNotIn(
            "max_tec >= 256",
            (ROOT / "docs/development/p3b-bus-off-manual-test.md").read_text(),
        )

    def test_manual_acceptance_includes_progress_and_containment_evidence(self):
        expected = validator.EXPECTED_ACCEPTANCE
        self.assertEqual(expected["warning_observed"], 1)
        self.assertEqual(expected["error_passive_observed"], 1)
        self.assertEqual(expected["tx_submit_count"], 1)
        self.assertEqual(expected["cancel_timeout_observed"], 0)
        self.assertEqual(expected["post_cleanup_pads_disconnected"], 1)
        self.assertEqual(expected["retrigger_rejected_count_delta"], 1)


if __name__ == "__main__":
    unittest.main()
