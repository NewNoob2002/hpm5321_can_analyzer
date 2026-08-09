import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/phase3/collect_usb_hotplug.py"
SPEC = importlib.util.spec_from_file_location("collect_usb_hotplug", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UsbHotplugCollectorTests(unittest.TestCase):
    def test_recovery_smoke_retries_transient_enumeration_failure(self):
        failed = {
            "exit_code": 2,
            "stdout": "",
            "stderr": "FAIL device absent or inaccessible",
        }
        passed = {"exit_code": 0, "stdout": "PASS", "stderr": ""}
        with mock.patch.object(MODULE, "_run_smoke", side_effect=[failed, passed]):
            result = MODULE._run_smoke_with_retry(
                Path("/tmp/smoke"), 1024, timeout_seconds=1.0, retry_ms=1
            )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(result["attempts"], [failed, passed])
        self.assertGreaterEqual(result["recovery_ms"], 0)

    def test_finds_only_matching_vid_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            sysfs = Path(temporary)
            for name, vid, pid in (
                ("7-1.4", "34b7", "1236"),
                ("7-1", "05e3", "0610"),
                ("1-1", "34b7", "9999"),
            ):
                device = sysfs / name
                device.mkdir()
                (device / "idVendor").write_text(vid, encoding="ascii")
                (device / "idProduct").write_text(pid, encoding="ascii")
            self.assertEqual(
                MODULE.find_usb_devices(sysfs, "34B7", "1236"),
                [sysfs / "7-1.4"],
            )

    def test_missing_attribute_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            sysfs = Path(temporary)
            (sysfs / "interface-only").mkdir()
            self.assertEqual(MODULE.find_usb_devices(sysfs, "34b7", "1236"), [])

    def test_maps_sysfs_bus_and_device_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            device = Path(temporary)
            (device / "busnum").write_text("7\n", encoding="ascii")
            (device / "devnum").write_text("110\n", encoding="ascii")
            self.assertEqual(
                MODULE.usb_device_node(device), Path("/dev/bus/usb/007/110")
            )

    def test_external_executable_path_remains_absolute(self):
        self.assertEqual(
            MODULE._display_path(Path("/opt/tools/smoke"), Path("/repo")),
            "/opt/tools/smoke",
        )

    def test_two_cycles_require_disconnect_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = root / "sysfs"
            sysfs.mkdir()
            device = sysfs / "7-1.4"

            def connect():
                device.mkdir()
                (device / "idVendor").write_text("34b7", encoding="ascii")
                (device / "idProduct").write_text("1236", encoding="ascii")

            connect()
            smoke = root / "smoke.sh"
            smoke.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            smoke.chmod(0o755)

            def cycle_device():
                for _ in range(2):
                    time.sleep(0.1)
                    shutil.rmtree(device)
                    time.sleep(0.05)
                    connect()

            thread = threading.Thread(target=cycle_device)
            thread.start()
            output = root / "evidence.json"
            args = SimpleNamespace(
                root=root,
                sysfs_root=sysfs,
                vid="34b7",
                pid="1236",
                cycles=2,
                poll_ms=5,
                minimum_disconnect_ms=10,
                overall_timeout_seconds=3,
                recovery_timeout_seconds=1.0,
                smoke_retry_ms=5,
                smoke_bytes=1024,
                smoke_executable=smoke,
                output=output,
                operator="test",
            )
            self.assertEqual(MODULE.collect(args), 0)
            thread.join()
            evidence = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(evidence["status"], "PASS")
            self.assertEqual(evidence["completed_cycles"], 2)
            self.assertEqual(len(evidence["cycles"]), 2)
            self.assertTrue(
                all(item["recovery_smoke"]["exit_code"] == 0 for item in evidence["cycles"])
            )
            self.assertTrue(
                all(item["recovery_smoke"]["attempt_count"] == 1 for item in evidence["cycles"])
            )


if __name__ == "__main__":
    unittest.main()
