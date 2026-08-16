import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ci import check_reproducible_build_contract as contract
from scripts.env import normalize_build_paths


class ReproducibleBuildContractTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(
            os.environ,
            {
                "HPM_SDK_BASE": "/opt/test-hpm-sdk",
                "GNURISCV_TOOLCHAIN_PATH": "/opt/test-riscv-toolchain",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def compile_flags(self, build):
        roots = {
            "source": contract.ROOT.resolve(),
            "build": build.resolve(),
            "sdk": Path(os.environ["HPM_SDK_BASE"]).resolve(),
            "toolchain": Path(os.environ["GNURISCV_TOOLCHAIN_PATH"]).resolve(),
        }
        return " ".join(
            f"-f{kind}-prefix-map={roots[name]}={stable}"
            for kind in contract.KINDS
            for name, stable in contract.STABLE_ROOTS.items()
        )

    def test_compile_contract_covers_app_easylogger_and_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            path = build / "compile_commands.json"
            flags = self.compile_flags(build)
            sources = (
                contract.ROOT / "USER/src/main.c",
                contract.ROOT / "third_party/easylogger/src/elog.c",
                contract.ROOT / "boards/hpm5321_custom/board.c",
                Path(os.environ["HPM_SDK_BASE"]) / "drivers/src/hpm_mcan_drv.c",
            )
            entries = [
                {"file": str(source), "command": f"cc {flags} -c {source}"}
                for source in sources
            ]
            path.write_text(json.dumps(entries))
            self.assertEqual(
                contract.verify_compile_database(path),
                {"all": 4, "sdk": 1, "app": 1, "easylogger": 1, "board": 1},
            )

    def test_missing_map_is_rejected_by_real_control_flow(self):
        entry = {
            "file": str(contract.ROOT / "USER/src/main.c"),
            "command": "cc -c main.c",
        }
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            path = build / "compile_commands.json"
            path.write_text(json.dumps([entry]))
            with self.assertRaisesRegex(ValueError, "missing exact file source map"):
                contract.verify_compile_database(path)

    def test_sdk_translation_unit_missing_toolchain_map_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            path = build / "compile_commands.json"
            flags = self.compile_flags(build).replace(
                f"-ffile-prefix-map={Path(os.environ['GNURISCV_TOOLCHAIN_PATH']).resolve()}"
                "=/toolchain/riscv",
                "",
            )
            source = Path(os.environ["HPM_SDK_BASE"]) / "drivers/src/hpm_mcan_drv.c"
            path.write_text(json.dumps([
                {"file": str(source), "command": f"cc {flags} -c {source}"}
            ]))
            with self.assertRaisesRegex(ValueError, "missing exact file toolchain map"):
                contract.verify_compile_database(path)

    def test_map_normalizer_removes_checkout_sdk_and_build_paths(self):
        build = normalize_build_paths.ROOT / "build/example"
        sdk = Path("/home/example/hpm_sdk")
        text = f"{normalize_build_paths.ROOT}/USER {build}/obj {sdk}/driver"
        with mock.patch.dict(os.environ, {"HPM_SDK_BASE": str(sdk)}, clear=False):
            normalized = normalize_build_paths.normalized_text(text, build)
        self.assertEqual(
            normalized,
            "/src/hpm5321_can_analyzer/USER /build/hpm5321_can_analyzer/obj /sdk/hpm_sdk/driver",
        )


if __name__ == "__main__":
    unittest.main()
