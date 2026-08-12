from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.phase3.collect_post_hil_health import (
    _sample_target,
    collect,
    load_hil_evidence,
    parse_snapshot,
    validate_snapshot,
)


def healthy_output() -> str:
    return (
        "P3A_USB magic=5553424f version=1 priority=4 irq_requests=1 initialized=1 "
        "online=1 connected=1 configured=1 generation=3 connects=2 resets=1 "
        "disconnects=1 configurations=2 queue_sends=205 queue_drops=0 stale=1 "
        "rx_completions=100 tx_completions=100 rx_bytes=204800 tx_bytes=204800 "
        "transfer_errors=0 out_armed=1 in_flight=0 stack=256\n"
        "P3B_MCAN magic=4d43414e version=1 mode=1 initialized=1 online=1 "
        "tx_armed=0 source_clock_hz=80000000 control_status=00000020 "
        "nominal_bit_timing=06000a03 priority=4 interrupts=0 frames_received=0 frames_published=0 "
        "invalid_frames=0 queue_sends=0 queue_drops=0 ring_count=0 ring_drops=0 "
        "ring_high_watermark=0 bus_off=0 warning=0 error_passive=0 "
        "recovery_attempts=0 tx_rejected_disarmed=0 tx_rejected_invalid=0 "
        "activity_drops=0 stack=256 last_rx_tick=0\n"
        "P3A_HEALTH boot_magic=424f4f54 boot_tick=100 reset=00000010 "
        "health_magic=484c5448 health_version=1 heartbeat=100 drops=0 health_stack=300 "
        "last_tick=10000 fault_magic=00000000 fault_reason=0 watchdog_magic=57444756 "
        "watchdog_version=1 required=0000000f missing=00000000 stall=00000000 "
        "evaluations=100 healthy=100 alloc_magic=414c4c43 alloc_version=1 "
        "alloc_frozen=1 allocations=1 post_freeze_allocations=0\n"
    )


class PostHilHealthCollectorTests(unittest.TestCase):
    def test_parses_and_validates_joint_snapshot(self) -> None:
        snapshot = parse_snapshot(healthy_output())

        validate_snapshot(snapshot, 128)

        self.assertEqual(snapshot["usb_owner"]["rx_bytes"], 204800)
        self.assertEqual(snapshot["mcan0_owner"]["mode"], 1)
        self.assertEqual(snapshot["rtos_health"]["required"], 0xF)

    def test_fails_closed_on_usb_mcan_or_rtos_health_violation(self) -> None:
        for broken in (
            healthy_output().replace("queue_drops=0", "queue_drops=1"),
            healthy_output().replace("tx_armed=0", "tx_armed=1"),
            healthy_output().replace("healthy=100", "healthy=99"),
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(RuntimeError):
                    validate_snapshot(parse_snapshot(broken), 128)

    def test_rejects_incomplete_gdb_output(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "P3A_HEALTH"):
            parse_snapshot(healthy_output().split("P3A_HEALTH", 1)[0])

    @mock.patch("scripts.phase3.collect_post_hil_health.subprocess.run")
    def test_one_gdb_process_collects_both_records_in_one_halt(
        self, run: mock.Mock
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, healthy_output(), "")

        snapshot = _sample_target(Path("gdb"), Path("demo.elf"), 2331)

        self.assertEqual(snapshot["usb_owner"]["magic"], 0x5553424F)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command.count("monitor halt"), 1)
        self.assertEqual(command.count("monitor go"), 1)
        joined = " ".join(command)
        self.assertIn("g_app_usb_owner_state", joined)
        self.assertIn("g_app_mcan0_owner_state", joined)
        self.assertIn("g_app_health_state", joined)
        self.assertIn("g_app_watchdog_state", joined)

    def test_hil_link_requires_pass_identity_and_matching_elf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "hil.json"
            elf_hash = hashlib.sha256(b"elf").hexdigest()
            path.write_text(
                json.dumps(
                    {
                        "test_id": "T-USB-006",
                        "status": "PASS",
                        "completed_at": "2026-08-10T00:00:00+00:00",
                        "firmware_manifest": {"elf_sha256": elf_hash},
                        "device": {
                            "topology_path": "7-1.4",
                            "serial": "HPM5321-P3A-001",
                        },
                        "evidence_boundary": {"verdict": "PASS"},
                    }
                ),
                encoding="utf-8",
            )

            linked = load_hil_evidence(path, root, elf_hash)
            self.assertEqual(linked["test_references"], ["T-USB-006"])
            self.assertEqual(
                linked["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
            )
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                load_hil_evidence(path, root, "0" * 64)

    def test_hil_link_rejects_stale_or_unsupported_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "hil.json"
            elf_hash = hashlib.sha256(b"elf").hexdigest()
            completed = datetime.now(timezone.utc) - timedelta(minutes=10)
            document = {
                "test_id": "T-USB-006",
                "status": "PASS",
                "completed_at": completed.isoformat(),
                "firmware_manifest": {"elf_sha256": elf_hash},
                "device": {
                    "topology_path": "7-1.4",
                    "serial": "HPM5321-P3A-001",
                },
                "evidence_boundary": {"verdict": "PASS"},
            }
            path.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "freshness window"):
                load_hil_evidence(
                    path, root, elf_hash, datetime.now(timezone.utc), 300.0
                )

            document["test_id"] = "T-RTOS-005"
            document["completed_at"] = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unsupported test identity"):
                load_hil_evidence(path, root, elf_hash)

    def test_collect_preflight_failure_writes_not_qualified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(
                root=root,
                output=Path("evidence.json"),
                elf=Path("missing.elf"),
                firmware_manifest=Path("missing-manifest.json"),
                hil_evidence=[],
                operator="test",
                minimum_stack_words=128,
                maximum_hil_age_seconds=300.0,
                sysfs_root=Path("sysfs"),
                probe_serial="probe",
                device="target",
                gdb_server=Path("server"),
                jtag_khz=4000,
                port=2331,
                server_start_seconds=0.01,
                gdb=Path("gdb"),
            )

            self.assertEqual(collect(args), 1)

            evidence = json.loads((root / "evidence.json").read_text())
            self.assertEqual(evidence["status"], "FAIL")
            self.assertEqual(
                evidence["evidence_boundary"]["verdict"], "NOT_QUALIFIED"
            )
            self.assertIn("ELF does not exist", evidence["failure"])


if __name__ == "__main__":
    unittest.main()
