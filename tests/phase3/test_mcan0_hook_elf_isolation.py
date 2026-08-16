from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_checker():
    path = ROOT / "scripts/env/check_mcan0_hook_isolation.py"
    spec = importlib.util.spec_from_file_location("mcan0_hook_isolation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load_checker()


class Mcan0HookElfIsolationTests(unittest.TestCase):
    def make_build(self, root: Path, enabled: bool) -> Path:
        build = root / ("debug" if enabled else "release")
        (build / "output").mkdir(parents=True)
        (build / "output/demo.elf").write_bytes(b"ELF fixture")
        state = "ON" if enabled else "OFF"
        value = 1 if enabled else 0
        (build / "CMakeCache.txt").write_text(
            f"APP_MCAN0_BUS_OFF_TEST_HOOK:BOOL={state}\n"
        )
        (build / "compile_commands.json").write_text(json.dumps([{
            "file": str(ROOT / checker.SOURCE_SUFFIX),
            "arguments": ["cc", f"-DAPP_MCAN0_BUS_OFF_TEST_HOOK={value}"],
        }]))
        return build

    def test_release_rejects_hook_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            build = self.make_build(Path(directory), False)
            original = checker.nm_symbols
            checker.nm_symbols = lambda _elf, _nm: {
                "g_app_mcan0_bus_off_test_result": 104
            }
            try:
                with self.assertRaisesRegex(SystemExit, "leaks bus-off test symbols"):
                    checker.verify_build(build, False, "nm")
            finally:
                checker.nm_symbols = original

    def test_debug_requires_exact_abi_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            build = self.make_build(Path(directory), True)
            original = checker.nm_symbols
            checker.nm_symbols = lambda _elf, _nm: dict(checker.ABI_SYMBOL_SIZES)
            try:
                checker.verify_build(build, True, "nm")
            finally:
                checker.nm_symbols = original

    def test_debug_rejects_wrong_result_size(self):
        with tempfile.TemporaryDirectory() as directory:
            build = self.make_build(Path(directory), True)
            symbols = dict(checker.ABI_SYMBOL_SIZES)
            symbols["g_app_mcan0_bus_off_test_result"] = 100
            original = checker.nm_symbols
            checker.nm_symbols = lambda _elf, _nm: symbols
            try:
                with self.assertRaisesRegex(SystemExit, "size mismatch"):
                    checker.verify_build(build, True, "nm")
            finally:
                checker.nm_symbols = original


if __name__ == "__main__":
    unittest.main()
