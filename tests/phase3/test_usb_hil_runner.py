from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.phase3.run_usb_hil import (
    BACKPRESSURE_DELAYS_MS,
    EP_IN,
    EP_OUT,
    FRAGMENT_SIZES,
    LIBUSB_ERROR_PIPE,
    RESET_PENDING_SIZES,
    DEFAULT_FS_MANIFEST,
    USB_DESCRIPTOR_TYPE_CONFIGURATION,
    USB_DESCRIPTOR_TYPE_DEVICE_QUALIFIER,
    USB_DESCRIPTOR_TYPE_OTHER_SPEED,
    build_matrix_cases,
    build_parser,
    loopback_evidence_boundary,
    matrix_evidence_boundaries,
    minimums_met,
    run_fs_fallback,
    validate_fs_descriptor_set,
)


class FakeUsbSession:
    def __init__(self, *_args: object) -> None:
        self.pending = b""
        self.reset_count = 0
        self.halted_endpoints: set[int] = set()

    def __enter__(self) -> "FakeUsbSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

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
        self.halted_endpoints.clear()
        self.reset_count += 1
        return {
            "libusb_result": 0,
            "libusb_result_name": "LIBUSB_SUCCESS / LIBUSB_TRANSFER_COMPLETED",
            "reopen_ms": 1.0,
        }

    def endpoint_halted(self, endpoint: int) -> bool:
        return endpoint in self.halted_endpoints

    def set_endpoint_halt(self, endpoint: int) -> None:
        self.halted_endpoints.add(endpoint)

    def expect_endpoint_stall(self, endpoint: int) -> dict[str, object]:
        assert endpoint in self.halted_endpoints
        return {
            "bulk_result": LIBUSB_ERROR_PIPE,
            "bulk_result_name": "LIBUSB_ERROR_PIPE",
            "transferred_bytes": 0,
        }

    def clear_endpoint_halt(self, endpoint: int) -> None:
        self.halted_endpoints.remove(endpoint)

    def read_descriptor(self, descriptor_type: int, _length: int = 512) -> bytes:
        if descriptor_type == USB_DESCRIPTOR_TYPE_DEVICE_QUALIFIER:
            return bytes((10, 6, 0, 2, 0, 0, 0, 64, 1, 0))
        descriptor = bytearray(
            (9, descriptor_type, 32, 0, 1, 1, 0, 0x80, 100)
        )
        descriptor.extend((9, 4, 0, 0, 2, 0xFF, 0xFF, 0, 4))
        packet_size = (
            64 if descriptor_type == USB_DESCRIPTOR_TYPE_CONFIGURATION else 512
        )
        for endpoint in (EP_IN, EP_OUT):
            descriptor.extend(
                (7, 5, endpoint, 2, packet_size & 0xFF, packet_size >> 8, 0)
            )
        return bytes(descriptor)


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
            + len(RESET_PENDING_SIZES)
            + 2,
        )
        self.assertEqual(
            {case.category for case in cases},
            {"fragmentation", "backpressure", "reset", "endpoint_halt"},
        )
        self.assertEqual(session.reset_count, 10 + len(RESET_PENDING_SIZES))
        self.assertFalse(session.pending)
        self.assertFalse(session.halted_endpoints)
        halt_results = results[-2:]
        self.assertEqual(
            {result["endpoint"] for result in halt_results}, {"0x01", "0x81"}
        )
        self.assertTrue(
            all(result["bulk_result"] == LIBUSB_ERROR_PIPE for result in halt_results)
        )
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

    def test_forced_fs_validates_dual_speed_descriptor_set(self) -> None:
        result = validate_fs_descriptor_set(FakeUsbSession())

        self.assertEqual(
            result["current_endpoint_mps"], {"0x81": 64, "0x01": 64}
        )
        self.assertEqual(
            result["other_speed_endpoint_mps"], {"0x81": 512, "0x01": 512}
        )

    def test_forced_fs_cli_uses_dedicated_manifest_by_default(self) -> None:
        args = build_parser().parse_args(["fs-fallback"])

        self.assertEqual(args.firmware_manifest, DEFAULT_FS_MANIFEST)

    def test_matrix_does_not_overstate_referenced_test_ids(self) -> None:
        boundaries = matrix_evidence_boundaries()

        self.assertEqual(
            set(boundaries), {"T-USB-005", "T-USB-008", "T-USB-010"}
        )
        self.assertEqual(boundaries["T-USB-005"]["verdict"], "PARTIAL")
        self.assertEqual(boundaries["T-USB-008"]["verdict"], "PARTIAL")
        self.assertEqual(boundaries["T-USB-010"]["verdict"], "PASS")
        self.assertIn("protocol-frame", boundaries["T-USB-005"]["not_covered"])
        self.assertIn("queue/drop", boundaries["T-USB-008"]["not_covered"])
        self.assertIn("real IN/OUT endpoint HALT", boundaries["T-USB-010"]["covered"])
        self.assertIn("protocol/session", boundaries["T-USB-010"]["not_covered"])
        self.assertTrue(
            all(
                item["verdict"] == "NOT_QUALIFIED"
                for item in matrix_evidence_boundaries("NOT_QUALIFIED").values()
            )
        )

    def fs_args(self, output: Path) -> argparse.Namespace:
        return argparse.Namespace(
            output=output,
            firmware_manifest=Path("manifest.json"),
            sysfs_root=Path("sysfs"),
            bytes=4097,
            seed=0x5321,
            timeout_ms=3000,
            recovery_timeout_seconds=15.0,
        )

    @mock.patch("scripts.phase3.run_usb_hil.UsbSession", FakeUsbSession)
    @mock.patch("scripts.phase3.run_usb_hil.run_metadata")
    def test_fs_fallback_requires_forced_fs_manifest(self, metadata: mock.Mock) -> None:
        metadata.return_value = {
            "firmware_manifest": {
                "build_options": {"APP_USB_FORCE_FULL_SPEED": False}
            },
            "device": {"speed_mbps": "12"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "fs.json"

            self.assertEqual(run_fs_fallback(self.fs_args(output)), 1)

            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["status"], "FAIL")
            self.assertEqual(
                evidence["evidence_boundary"]["verdict"], "NOT_QUALIFIED"
            )
            self.assertIn("not a forced Full-Speed", evidence["failure"])

    @mock.patch("scripts.phase3.run_usb_hil.UsbSession", FakeUsbSession)
    @mock.patch("scripts.phase3.run_usb_hil.run_metadata")
    def test_fs_fallback_requires_physical_12_mbps(self, metadata: mock.Mock) -> None:
        metadata.return_value = {
            "firmware_manifest": {
                "build_options": {"APP_USB_FORCE_FULL_SPEED": True}
            },
            "device": {"speed_mbps": "480"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "fs.json"

            self.assertEqual(run_fs_fallback(self.fs_args(output)), 1)

            evidence = json.loads(output.read_text())
            self.assertIn("expected physical Full-Speed 12 Mbps", evidence["failure"])

    @mock.patch("scripts.phase3.run_usb_hil.UsbSession", FakeUsbSession)
    @mock.patch("scripts.phase3.run_usb_hil.run_metadata")
    def test_fs_fallback_passes_only_after_echo(self, metadata: mock.Mock) -> None:
        metadata.return_value = {
            "firmware_manifest": {
                "build_options": {"APP_USB_FORCE_FULL_SPEED": True}
            },
            "device": {"speed_mbps": "12"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "fs.json"

            self.assertEqual(run_fs_fallback(self.fs_args(output)), 0)

            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["status"], "PASS")
            self.assertEqual(evidence["verified_echo_bytes"], 4097)
            self.assertTrue(evidence["speed_verified"])
            self.assertTrue(evidence["echo_verified"])
            self.assertIn("descriptor_validation", evidence)
            self.assertEqual(
                evidence["evidence_boundary"]["verdict"], "PARTIAL"
            )


if __name__ == "__main__":
    unittest.main()
