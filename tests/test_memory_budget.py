import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("memory_budget", ROOT / "scripts/env/check_memory_budget.py")
memory_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory_budget)

class MemoryBudgetTests(unittest.TestCase):
    def write_map(self, directory, include_flash=True):
        path = Path(directory) / "demo.map"
        flash_region = (
            "FLASH            0x0000000080000000 0x0000000000100000 xr\n"
            if include_flash
            else ""
        )
        flash_section = (
            ".text            0x0000000080000000 0x1000\n"
            if include_flash
            else ""
        )
        path.write_text(
            f"""Memory Configuration

Name             Origin             Length             Attributes
{flash_region}\
ILM              0x0000000000000000 0x0000000000020000 xrw
DLM              0x0000000000080300 0x000000000001fd00 xrw
AHB_SRAM         0x00000000f0400000 0x0000000000008000 xrw

Linker script and memory map
{flash_section}\
.fast            0x0000000000000000 0x2000
.data            0x0000000000080300 0x100
.bss             0x0000000000080600 0x1000
.heap            0x0000000000081600 0x4000
.stack           0x0000000000085600 0x4000
.ahb_sram        0x00000000f0400000 0xa00
.debug_info      0x0000000000000000 0x31a12
.comment         0x0000000000000000 0x2d
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

    def test_ram_map_without_flash_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            regions, usage, failures = memory_budget.check(
                self.write_map(directory, include_flash=False)
            )
        self.assertNotIn("FLASH", regions)
        self.assertNotIn("FLASH", usage)
        self.assertEqual(usage["ILM"], 0x2000)
        self.assertFalse(failures)

    def test_still_requires_all_ram_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_map(directory, include_flash=False)
            path.write_text(path.read_text().replace(
                "AHB_SRAM         0x00000000f0400000 "
                "0x0000000000008000 xrw\n",
                "",
            ))
            with self.assertRaisesRegex(ValueError, "AHB_SRAM"):
                memory_budget.check(path)

    def test_region_usage_includes_alignment_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            _, usage, _ = memory_budget.check(self.write_map(directory))
        section_size_sum = 0x100 + 0x1000 + 0x4000 + 0x4000
        self.assertEqual(usage["DLM"], section_size_sum + 0x200)

    def test_nonalloc_debug_sections_do_not_consume_zero_origin_ilm(self):
        with tempfile.TemporaryDirectory() as directory:
            _, usage, failures = memory_budget.check(
                self.write_map(directory, include_flash=False)
            )
        self.assertEqual(usage["ILM"], 0x2000)
        self.assertFalse(failures)

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

    def test_bus_off_debug_profile_only_relaxes_ilm(self):
        self.assertEqual(memory_budget.BUS_OFF_DEBUG_LIMITS["ILM"], 126 * 1024)
        for region in ("FLASH", "DLM", "AHB_SRAM"):
            self.assertEqual(
                memory_budget.BUS_OFF_DEBUG_LIMITS[region],
                memory_budget.DEFAULT_LIMITS[region],
            )

if __name__ == "__main__":
    unittest.main()
