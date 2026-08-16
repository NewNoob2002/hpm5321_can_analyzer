from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL = timezone(timedelta(hours=8))


def load_reconciler():
    path = ROOT / "scripts/phase3/reconcile_p3b_analyzer.py"
    spec = importlib.util.spec_from_file_location("p3b_analyzer_reconciler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reconciler = load_reconciler()


class P3bAnalyzerReconciliationTests(unittest.TestCase):
    def timestamp_ns(self, text: str) -> int:
        value = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=LOCAL
        )
        return (
            int(value.replace(microsecond=0).timestamp()) * 1_000_000_000
            + value.microsecond * 1_000
        )

    def write_csv(
        self, path: Path, fieldnames: list[str], rows: list[dict[str, object]]
    ) -> None:
        with path.open("w", newline="", encoding="ascii") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def fixture(self, directory: Path) -> None:
        (directory / "summary.json").write_text(
            json.dumps(
                {
                    "warmup_seconds": 5,
                    "duration_seconds": 180,
                    "frames": 3,
                    "frames_per_second": 1.0,
                    "event_gaps": 0,
                    "channel_gaps": 0,
                    "forward_missing_records": 0,
                    "backward_or_duplicate_records": 0,
                    "device_drop_total": 0,
                    "measurement_queue_drops": 0,
                    "measurement_ring_drops": 0,
                    "data_loss_events": 0,
                    "data_loss_dropped": 0,
                    "latency_ns_p95": 1_000_000,
                    "fit_residual_ns_p95": 1_000,
                    "host_acceptance": False,
                }
            )
        )
        self.write_csv(
            directory / "diagnostics.csv",
            ["host_poll_ns", "phase"],
            [
                {
                    "host_poll_ns": self.timestamp_ns(
                        "2026-08-15 12:00:00.005"
                    ),
                    "phase": "measurement_start",
                },
                {
                    "host_poll_ns": self.timestamp_ns(
                        "2026-08-15 12:00:00.035"
                    ),
                    "phase": "measurement_end",
                },
            ],
        )
        self.write_csv(
            directory / "frames.csv",
            [
                "host_ingest_ns",
                "device_tick",
                "channel_sequence",
                "arbitration_id",
                "flags",
                "dlc",
                "device_drop_total",
                "event_sequence",
                "payload_hex",
            ],
            [
                {
                    "host_ingest_ns": self.timestamp_ns(
                        f"2026-08-15 12:00:00.0{value}0"
                    ),
                    "device_tick": value,
                    "channel_sequence": value,
                    "arbitration_id": 0x7FF,
                    "flags": 0,
                    "dlc": 0,
                    "device_drop_total": 0,
                    "event_sequence": value,
                    "payload_hex": "",
                }
                for value in (1, 2, 3)
            ],
        )
        (directory / "analyzer-log.txt").write_text(
            "\n".join(
                [
                    "26-08-15 12:00:00.000 Send[7FF]: ",
                    "26-08-15 12:00:00.010 Send[7FF]: ",
                    "26-08-15 12:00:00.020 Send[7FF]: ",
                    "26-08-15 12:00:00.030 Send[7FF]: ",
                    "26-08-15 12:00:00.040 Send[7FF]: ",
                ]
            )
            + "\n",
            encoding="ascii",
        )

    def test_exact_count_order_and_content_pass_with_timestamp_limitation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "PASS_WITH_LIMITATION")
        self.assertEqual(result["frame_reconciliation"], "PASS")
        self.assertEqual(
            result["record_order_reconciliation"],
            "NOT_DISTINGUISHABLE_IDENTICAL_FRAMES",
        )
        self.assertEqual(result["timestamp_reconciliation"], "PASS_WITH_LIMITATION")
        self.assertEqual(result["analyzer_measurement_records"], 3)
        self.assertEqual(result["dut_frame_records"], 3)
        self.assertFalse(result["high_rate_analyzer_coverage"])

    def test_count_mismatch_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            lines = (directory / "analyzer-log.txt").read_text().splitlines()
            (directory / "analyzer-log.txt").write_text(
                "\n".join(lines[:2] + lines[3:]) + "\n"
            )
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "DUT active-span analyzer count does not match DUT frames",
            result["errors"],
        )

    def test_identifier_mismatch_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            text = (directory / "analyzer-log.txt").read_text()
            (directory / "analyzer-log.txt").write_text(
                text.replace("12:00:00.020 Send[7FF]", "12:00:00.020 Send[123]")
            )
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["id_mismatches"], 1)

    def test_dut_drop_or_gap_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            summary = json.loads((directory / "summary.json").read_text())
            summary["channel_gaps"] = 1
            (directory / "summary.json").write_text(json.dumps(summary))
            result = reconciler.reconcile(directory)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "low-rate DUT run reports nonzero channel_gaps", result["errors"]
        )


if __name__ == "__main__":
    unittest.main()
