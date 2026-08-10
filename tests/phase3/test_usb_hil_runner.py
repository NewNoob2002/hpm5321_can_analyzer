from __future__ import annotations

import random
import unittest

from scripts.phase3.run_usb_hil import (
    BACKPRESSURE_DELAYS_MS,
    FRAGMENT_SIZES,
    RESET_PENDING_SIZES,
    build_matrix_cases,
    loopback_evidence_boundary,
    matrix_evidence_boundaries,
    minimums_met,
)


class FakeUsbSession:
    def __init__(self) -> None:
        self.pending = b""
        self.reset_count = 0

    def write(self, payload: bytes) -> None:
        assert not self.pending
        self.pending = payload

    def read(self, size: int) -> bytes:
        assert len(self.pending) == size
        payload = self.pending
        self.pending = b""
        return payload

    def echo(self, payload: bytes) -> None:
        self.write(payload)
        assert self.read(len(payload)) == payload

    def reset_and_reopen(self) -> dict[str, object]:
        self.pending = b""
        self.reset_count += 1
        return {
            "libusb_result": 0,
            "libusb_result_name": "LIBUSB_SUCCESS / LIBUSB_TRANSFER_COMPLETED",
            "reopen_ms": 1.0,
        }


class UsbHilRunnerTests(unittest.TestCase):
    def test_matrix_covers_boundaries_backpressure_and_reset(self) -> None:
        session = FakeUsbSession()
        cases = build_matrix_cases(
            random.Random(0x5321), sleep=lambda _seconds: None
        )

        results = [case.action(session) for case in cases]

        self.assertEqual(
            len(cases),
            len(FRAGMENT_SIZES)
            + len(BACKPRESSURE_DELAYS_MS)
            + 10
            + len(RESET_PENDING_SIZES),
        )
        self.assertEqual(
            {case.category for case in cases},
            {"fragmentation", "backpressure", "reset"},
        )
        self.assertEqual(session.reset_count, 10 + len(RESET_PENDING_SIZES))
        self.assertFalse(session.pending)
        self.assertTrue(
            all(
                result["verified_bytes"] > 0
                for result in results[: len(FRAGMENT_SIZES)]
            )
        )

    def test_loopback_requires_both_thresholds(self) -> None:
        self.assertTrue(minimums_met(10, 60.0, 10, 60.0))
        self.assertFalse(minimums_met(9, 60.0, 10, 60.0))
        self.assertFalse(minimums_met(10, 59.9, 10, 60.0))
        self.assertEqual(loopback_evidence_boundary()["verdict"], "PASS")
        self.assertIn(
            "protocol/session", loopback_evidence_boundary()["not_covered"]
        )

    def test_matrix_does_not_overstate_referenced_test_ids(self) -> None:
        boundaries = matrix_evidence_boundaries()

        self.assertEqual(
            set(boundaries), {"T-USB-005", "T-USB-008", "T-USB-010"}
        )
        self.assertTrue(
            all(item["verdict"] == "PARTIAL" for item in boundaries.values())
        )
        self.assertIn("protocol-frame", boundaries["T-USB-005"]["not_covered"])
        self.assertIn("queue/drop", boundaries["T-USB-008"]["not_covered"])
        self.assertIn("HALT/STALL", boundaries["T-USB-010"]["not_covered"])
        self.assertTrue(
            all(
                item["verdict"] == "NOT_QUALIFIED"
                for item in matrix_evidence_boundaries("NOT_QUALIFIED").values()
            )
        )


if __name__ == "__main__":
    unittest.main()
