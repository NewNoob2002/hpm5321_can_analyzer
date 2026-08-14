import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("memory_budget", ROOT / "scripts/env/check_memory_budget.py")
memory_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory_budget)

class MemoryBudgetTests(unittest.TestCase):
    def write_map(self, directory):
        path = Path(directory) / "demo.map"
        path.write_text(
            """Memory Configuration

Name             Origin             Length             Attributes
FLASH            0x0000000080000000 0x0000000000100000 xr
ILM              0x0000000000000000 0x0000000000020000 xrw
DLM              0x0000000000080300 0x000000000001fd00 xrw
AHB_SRAM         0x00000000f0400000 0x0000000000008000 xrw

Linker script and memory map
.text            0x0000000080000000 0x1000
.fast            0x0000000000000000 0x2000
.data            0x0000000000080300 0x100
.bss             0x0000000000080600 0x1000
.heap            0x0000000000081600 0x4000
.stack           0x0000000000085600 0x4000
.ahb_sram        0x00000000f0400000 0xa00
"""
        )
        return path

    def test_parses_all_regions_and_dlm_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            regions, usage, failures = memory_budget.check(
                self.write_map(directory)
            )
        self.assertEqual(regions["DLM"][1], 130304)
        self.assertEqual(usage["DLM"], 0x9300)
        self.assertEqual(usage["AHB_SRAM"], 2560)
        self.assertFalse(failures)

    def test_region_usage_includes_alignment_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            _, usage, _ = memory_budget.check(self.write_map(directory))
        section_size_sum = 0x100 + 0x1000 + 0x4000 + 0x4000
        self.assertEqual(usage["DLM"], section_size_sum + 0x200)

    def test_limit_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, failures = memory_budget.check(
                self.write_map(directory),
                {**memory_budget.DEFAULT_LIMITS, "DLM": 1},
            )
        self.assertTrue(any(f.startswith("DLM ") for f in failures))

    def test_dlm_budget_requires_six_kib_free(self):
        self.assertEqual(
            memory_budget.DEFAULT_LIMITS["DLM"],
            130304 - 6 * 1024,
        )

if __name__ == "__main__":
    unittest.main()
