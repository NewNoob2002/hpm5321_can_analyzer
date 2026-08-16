from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(
    "docs/evidence/phase3/P3B-bus-off-attempt-2026-08-15.json"
)


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_bus_off_attempt.py"
    spec = importlib.util.spec_from_file_location(
        "p3b_bus_off_attempt_validator", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bBusOffAttemptTests(unittest.TestCase):
    def current_evidence(self) -> dict:
        return json.loads((ROOT / EVIDENCE).read_text())

    def write_evidence(self, directory: Path, value: dict) -> Path:
        path = directory / "attempt.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return path.relative_to(ROOT)

    def test_current_attempt_passes(self):
        self.assertEqual(validator.validate(ROOT, EVIDENCE), [])

    def test_attempt_cannot_claim_bus_off_or_open_gates(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            evidence["execution"]["outcome"] = "PASS"
            evidence["observed"]["bus_off_observed"] = 1
            evidence["gates"]["qualification_status"] = "PASS"
            evidence["gates"]["p4e_gate"] = "OPEN"
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn("bus-off attempt execution outcome mismatch", errors)
        self.assertIn("bus-off attempt observations mismatch", errors)
        self.assertIn("bus-off attempt gates mismatch", errors)

    def test_attempt_cannot_claim_an_active_fault_injector(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            evidence["hardware"]["active_fault_injector_present"] = True
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn("bus-off attempt hardware configuration mismatch", errors)

    def test_tampered_timeout_log_is_rejected_with_updated_package_hash(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            evidence = self.current_evidence()
            source_path = ROOT / evidence["package"]["path"]
            package_path = directory / "attempt.zip"
            with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(
                package_path, "w"
            ) as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == "timeout-dump-gdb.txt":
                        data = data.replace(b"max_tec = 128", b"max_tec = 255")
                    target.writestr(info, data)
            evidence["package"]["path"] = package_path.relative_to(ROOT).as_posix()
            evidence["package"]["sha256"] = hashlib.sha256(
                package_path.read_bytes()
            ).hexdigest()
            evidence["package"]["size"] = package_path.stat().st_size
            errors = validator.validate(
                ROOT, self.write_evidence(directory, evidence)
            )
        self.assertIn(
            "bus-off attempt member reference mismatch: timeout-dump-gdb.txt",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
