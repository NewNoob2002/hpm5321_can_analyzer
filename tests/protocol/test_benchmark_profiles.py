from __future__ import annotations

import json
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/approved-plan"


def load(name: str) -> dict[str, object]:
    return json.loads((PLAN / name).read_text(encoding="utf-8"))


class BenchmarkProfileTests(unittest.TestCase):
    def test_single_channel_mvp_profile_is_frozen_and_bounded(self) -> None:
        profile = load("bp-can-mvp-v1.json")
        rendered = json.dumps(profile, sort_keys=True)

        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["profile_id"], "BP-CAN-MVP-v1")
        self.assertEqual(profile["status"], "FROZEN")
        self.assertNotIn("TBD", rendered.upper())
        self.assertEqual(profile["channel"]["index"], 0)
        self.assertEqual(profile["channel"]["controller"], "MCAN0")
        self.assertEqual(profile["channel"]["frame_format"], "CLASSIC")
        self.assertEqual(profile["channel"]["nominal_bitrate_bps"], 1_000_000)
        self.assertFalse(profile["channel"]["can_fd"])
        self.assertEqual(profile["traffic"]["minimum_frame_rate_fps"], 6000)
        self.assertEqual(profile["traffic"]["target_bus_utilization_percent"], 80.0)
        self.assertTrue(
            math.isclose(
                sum(profile["traffic"]["standard_extended_ratio"].values()),
                1.0,
            )
        )
        self.assertTrue(
            math.isclose(
                sum(profile["traffic"]["dlc_distribution"].values()), 1.0
            )
        )
        self.assertEqual(profile["batch"]["maximum_records"], 32)
        self.assertEqual(profile["batch"]["maximum_wait_microseconds"], 1000)
        self.assertEqual(profile["measurement"]["duration_seconds"], 1800)
        self.assertGreaterEqual(profile["measurement"]["minimum_frames"], 10_800_000)
        self.assertEqual(profile["acceptance"]["device_drop_total"], 0)
        self.assertEqual(profile["acceptance"]["host_sequence_gaps"], 0)

    def test_latency_profile_inherits_mvp_and_freezes_calibration(self) -> None:
        profile = load("bp-latency-v1.json")
        rendered = json.dumps(profile, sort_keys=True)

        self.assertEqual(profile["profile_id"], "BP-LATENCY-v1")
        self.assertEqual(profile["status"], "FROZEN")
        self.assertEqual(profile["inherits_workload"], "BP-CAN-MVP-v1")
        self.assertNotIn("TBD", rendered.upper())
        self.assertEqual(profile["measurement"]["warmup_seconds"], 60)
        self.assertGreaterEqual(profile["measurement"]["minimum_samples"], 1_000_000)
        for field in (
            "ping_samples_before",
            "ping_samples_after",
            "ping_samples_every_60_seconds",
        ):
            self.assertGreaterEqual(profile["measurement"][field], 20)
        self.assertEqual(profile["measurement"]["reported_percentiles"], [50, 95, 99])
        self.assertIn("nearest-rank", profile["measurement"]["percentile_algorithm"])
        self.assertEqual(
            profile["acceptance"]["latency_p95_microseconds_max"], 5000
        )
        self.assertLessEqual(
            profile["acceptance"]["residual_plus_tick_quantization_microseconds_max"],
            profile["acceptance"]["latency_p95_microseconds_max"] * 0.2,
        )
        self.assertEqual(profile["acceptance"]["device_drop_total"], 0)

    def test_profiles_freeze_the_same_reference_host(self) -> None:
        workload = load("bp-can-mvp-v1.json")
        latency = load("bp-latency-v1.json")

        self.assertEqual(workload["reference_host"], latency["reference_host"])


if __name__ == "__main__":
    unittest.main()
