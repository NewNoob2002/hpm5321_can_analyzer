import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/phase0/storage_profile.py"
SPEC = importlib.util.spec_from_file_location("storage_profile", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_evidence(encoded_rate: int) -> dict:
    media = []
    for capacity in (4, 8, 16, 32):
        for vendor in ("vendor-a", "vendor-b"):
            media.append(
                {
                    "vendor": vendor,
                    "marketed_capacity_gb": capacity,
                    "filesystem": "FAT32",
                    "logical_sector_bytes": 512,
                    "status": "PASS",
                }
            )
    return {
        "schema_version": 1,
        "status": "PASS",
        "workload": {
            "profile": "BP-CAN-BETA-v1",
            "status": "FROZEN",
            "encoded_capture_bytes_per_s": encoded_rate,
        },
        "electrical": {
            "schematic_or_bom_ref": "SCH-1 rev A",
            "cs_active_level": 0,
            "detect_present_level": 0,
            "detect_absent_level": 1,
            "detect_pull": "external pull-up 10 kOhm",
            "debounce_ms": 20,
        },
        "media": media,
    }


class StorageProfileTests(unittest.TestCase):
    def test_calculates_queue_absorption(self):
        self.assertAlmostEqual(MODULE.queue_absorption_ms(640_000), 51.2)

    def test_valid_frozen_profile_and_evidence_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / MODULE.PROFILE_PATH
            profile.parent.mkdir(parents=True)
            profile.write_text(
                """| Key | Value |
|---|---|
| status | FROZEN |
| io_block_bytes | 4096 |
| queue_depth | 8 |
| encoded_capture_bytes_per_s | 640000 |
| queue_absorption_ms | 51.2 |
| operation_deadline_ms | 25.6 |
""",
                encoding="utf-8",
            )
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(valid_evidence(640_000)), encoding="utf-8"
            )
            self.assertEqual(MODULE.validate(root, evidence_path), [])

    def test_missing_media_vendor_and_unfrozen_profile_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / MODULE.PROFILE_PATH
            profile.parent.mkdir(parents=True)
            profile.write_text(
                """| Key | Value |
|---|---|
| status | BLOCKED |
| io_block_bytes | 4096 |
| queue_depth | 8 |
| encoded_capture_bytes_per_s | BLOCKED(P0S) |
| queue_absorption_ms | BLOCKED(P0S) |
| operation_deadline_ms | BLOCKED(P0S) |
""",
                encoding="utf-8",
            )
            evidence = valid_evidence(640_000)
            evidence["media"] = evidence["media"][:1]
            evidence_path = root / "evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            errors = MODULE.validate(root, evidence_path)
            self.assertTrue(any("status must be FROZEN" in item for item in errors))
            self.assertTrue(any("two vendors" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
