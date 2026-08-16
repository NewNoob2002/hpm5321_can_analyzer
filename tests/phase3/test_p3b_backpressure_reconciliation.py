from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_reconciler():
    path = ROOT / "scripts/phase3/reconcile_p3b_backpressure.py"
    spec = importlib.util.spec_from_file_location("p3b_backpressure_reconciler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reconciler = load_reconciler()


class P3bBackpressureReconciliationTests(unittest.TestCase):
    def write_csv(self, path: Path, fieldnames: list[str], rows: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def fixture(self, directory: Path) -> None:
        (directory / "summary.json").write_text(
            json.dumps(
                {
                    "device_drop_total": 0,
                    "measurement_queue_drops": 0,
                    "measurement_ring_drops": 0,
                    "forward_missing_records": 21,
                }
            )
        )
        self.write_csv(
            directory / "events.csv",
            ["host_ingest_ns", "event_sequence", "message_type"],
            [
                {"host_ingest_ns": 1, "event_sequence": 10, "message_type": 0x8001},
                {"host_ingest_ns": 2, "event_sequence": 11, "message_type": 0x8004},
                {"host_ingest_ns": 3, "event_sequence": 15, "message_type": 0x8005},
                {"host_ingest_ns": 4, "event_sequence": 16, "message_type": 0x8001},
            ],
        )
        self.write_csv(
            directory / "data_loss.csv",
            [
                "host_ingest_ns",
                "device_tick",
                "event_sequence",
                "channel",
                "source",
                "sequence_domain",
                "reason",
                "config_generation",
                "first_dropped_sequence",
                "last_dropped_sequence",
                "dropped_count",
            ],
            [
                {
                    "host_ingest_ns": 3,
                    "device_tick": 30,
                    "event_sequence": 15,
                    "channel": 255,
                    "source": 2,
                    "sequence_domain": 1,
                    "reason": 1,
                    "config_generation": 4,
                    "first_dropped_sequence": 12,
                    "last_dropped_sequence": 14,
                    "dropped_count": 3,
                }
            ],
        )
        self.write_csv(
            directory / "frames.csv",
            ["event_sequence"],
            [{"event_sequence": 10}, {"event_sequence": 16}],
        )

    def test_exact_event_domain_reconciliation_with_channel_boundary(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["usb_backpressure_recovery"], "PASS")
        self.assertEqual(result["event_sequence_reconciliation"], "PASS")
        self.assertEqual(result["channel_sequence_reconciliation"], "PARTIAL")
        self.assertEqual(result["observed_event_missing_count"], 3)
        self.assertEqual(result["declared_event_loss_count"], 3)
        self.assertEqual(result["flow_control_event_count"], 1)

    def test_unreported_event_gap_fails_reconciliation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            with (directory / "data_loss.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["last_dropped_sequence"] = "13"
            rows[0]["dropped_count"] = "2"
            self.write_csv(directory / "data_loss.csv", list(rows[0]), rows)
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["event_sequence_reconciliation"], "FAIL")


if __name__ == "__main__":
    unittest.main()
