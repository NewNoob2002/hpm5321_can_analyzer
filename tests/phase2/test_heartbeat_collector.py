import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/phase2/collect_heartbeat.py"
SPEC = importlib.util.spec_from_file_location("collect_heartbeat", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HeartbeatCollectorTests(unittest.TestCase):
    def test_validates_frozen_elf_hash(self):
        digest = "c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2"

        MODULE.validate_expected_sha256(digest, None)
        MODULE.validate_expected_sha256(digest, digest.upper())
        with self.assertRaisesRegex(RuntimeError, "64-digit"):
            MODULE.validate_expected_sha256(digest, "c3feef")
        with self.assertRaisesRegex(RuntimeError, "mismatch"):
            MODULE.validate_expected_sha256(digest, "0" * 64)

    def test_clamps_sleep_to_zero_after_slow_first_sample(self):
        self.assertEqual(MODULE._bounded_sleep_seconds(5.0, -0.25), 0.0)
        self.assertEqual(MODULE._bounded_sleep_seconds(5.0, 2.0), 2.0)
        self.assertEqual(MODULE._bounded_sleep_seconds(5.0, 8.0), 5.0)

    def test_parses_machine_readable_gdb_sample(self):
        sample = MODULE.parse_sample(
            "noise\nP2_SAMPLE boot=424f4f54 boot_tick=317000 "
            "reset=00000010 heartbeat=42 "
            "drops=0 stack=447 tick=504000000 fault_magic=00000000 "
            "fault_reason=0 evaluations=42 healthy=42 missing=00000000 "
            "stall=00000000 alloc_frozen=1 allocations=0 "
            "post_freeze_allocations=0 mcan_magic=50415353 mcan_priority=4 "
            "mcan_irqs=1024 mcan_submitted=1024 mcan_received=1024 "
            "mcan_matched=1024 mcan_queue_sends=1024 mcan_queue_drops=0 "
            "mcan_errors=00000000 mcan_terminal_faults=00000000 "
            "mcan_tx_errors=0 mcan_rx_errors=0 mcan_error_log=0 "
            "mcan_mismatches=0 mcan_timeouts=0 mcan_stack=335 "
            "mcan_cleanup_status=0 mcan_cccr=00000001 mcan_cleanup=1\n"
        )

        self.assertEqual(sample["boot"], 0x424F4F54)
        self.assertEqual(sample["boot_tick"], 317000)
        self.assertEqual(sample["reset"], 0x10)
        self.assertEqual(sample["heartbeat"], 42)
        self.assertEqual(sample["tick"], 504000000)

    def test_accepts_monotonic_healthy_samples(self):
        first = {
            "boot": 0x424F4F54,
            "boot_tick": 317000,
            "reset": 0x10,
            "heartbeat": 10,
            "drops": 0,
            "stack": 447,
            "tick": 120000000,
            "fault_magic": 0,
            "fault_reason": 0,
            "evaluations": 10,
            "healthy": 10,
            "missing": 0,
            "stall": 0,
            "alloc_frozen": 1,
            "allocations": 0,
            "post_freeze_allocations": 0,
            "mcan_magic": 0x50415353,
            "mcan_priority": 4,
            "mcan_irqs": 1024,
            "mcan_submitted": 1024,
            "mcan_received": 1024,
            "mcan_matched": 1024,
            "mcan_queue_sends": 1024,
            "mcan_queue_drops": 0,
            "mcan_errors": 0,
            "mcan_terminal_faults": 0,
            "mcan_tx_errors": 0,
            "mcan_rx_errors": 0,
            "mcan_error_log": 0,
            "mcan_mismatches": 0,
            "mcan_timeouts": 0,
            "mcan_stack": 335,
            "mcan_cleanup_status": 0,
            "mcan_cccr": 1,
            "mcan_cleanup": 1,
        }
        second = {
            **first,
            "heartbeat": 20,
            "tick": 240000000,
            "evaluations": 20,
            "healthy": 20,
        }

        MODULE.validate_sample(first, None, 128)
        MODULE.validate_sample(second, first, 128)

    def test_rejects_reset_fault_drop_stack_and_voter_failures(self):
        healthy = {
            "boot": 0x424F4F54,
            "boot_tick": 317000,
            "reset": 0x10,
            "heartbeat": 10,
            "drops": 0,
            "stack": 447,
            "tick": 120000000,
            "fault_magic": 0,
            "fault_reason": 0,
            "evaluations": 10,
            "healthy": 10,
            "missing": 0,
            "stall": 0,
            "alloc_frozen": 1,
            "allocations": 0,
            "post_freeze_allocations": 0,
            "mcan_magic": 0x50415353,
            "mcan_priority": 4,
            "mcan_irqs": 1024,
            "mcan_submitted": 1024,
            "mcan_received": 1024,
            "mcan_matched": 1024,
            "mcan_queue_sends": 1024,
            "mcan_queue_drops": 0,
            "mcan_errors": 0,
            "mcan_terminal_faults": 0,
            "mcan_tx_errors": 0,
            "mcan_rx_errors": 0,
            "mcan_error_log": 0,
            "mcan_mismatches": 0,
            "mcan_timeouts": 0,
            "mcan_stack": 335,
            "mcan_cleanup_status": 0,
            "mcan_cccr": 1,
            "mcan_cleanup": 1,
        }
        failures = (
            {**healthy, "boot": 0},
            {**healthy, "fault_magic": 0x4641554C},
            {**healthy, "drops": 1},
            {**healthy, "stack": 127},
            {**healthy, "missing": 2},
            {**healthy, "stall": 2},
            {**healthy, "healthy": 9},
            {**healthy, "alloc_frozen": 0},
            {**healthy, "post_freeze_allocations": 1},
            {**healthy, "mcan_magic": 0x4641494C},
            {**healthy, "mcan_priority": 3},
            {**healthy, "mcan_irqs": 1023},
            {**healthy, "mcan_submitted": 1023},
            {**healthy, "mcan_received": 1023},
            {**healthy, "mcan_matched": 1023},
            {**healthy, "mcan_queue_sends": 1023},
            {**healthy, "mcan_queue_drops": 1},
            {**healthy, "mcan_errors": 1},
            {**healthy, "mcan_terminal_faults": 1},
            {**healthy, "mcan_tx_errors": 1},
            {**healthy, "mcan_rx_errors": 1},
            {**healthy, "mcan_error_log": 1},
            {**healthy, "mcan_mismatches": 1},
            {**healthy, "mcan_timeouts": 1},
            {**healthy, "mcan_stack": 127},
            {**healthy, "mcan_cleanup_status": 1},
            {**healthy, "mcan_cccr": 0},
            {**healthy, "mcan_cleanup": 0},
        )
        for sample in failures:
            with self.subTest(sample=sample):
                with self.assertRaises(RuntimeError):
                    MODULE.validate_sample(sample, None, 128)

        with self.assertRaisesRegex(RuntimeError, "heartbeat did not advance"):
            MODULE.validate_sample(healthy, healthy, 128)

        reset = {
            **healthy,
            "boot_tick": healthy["boot_tick"] + 1,
            "heartbeat": healthy["heartbeat"] + 1,
            "tick": healthy["tick"] + 1,
            "evaluations": healthy["evaluations"] + 1,
            "healthy": healthy["healthy"] + 1,
        }
        with self.assertRaisesRegex(RuntimeError, "target reset detected"):
            MODULE.validate_sample(reset, healthy, 128)


if __name__ == "__main__":
    unittest.main()
