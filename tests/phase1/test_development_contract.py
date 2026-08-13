import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DevelopmentContractTests(unittest.TestCase):
    def test_required_presets_exist_and_export_compile_commands(self):
        data = json.loads((ROOT / "CMakePresets.json").read_text())
        configure = {item["name"]: item for item in data["configurePresets"]}
        build = {item["name"] for item in data["buildPresets"]}
        required = {
            "hpm5321-flash-debug",
            "hpm5321-flash-release",
            "hpm5321-ram-debug",
        }
        self.assertTrue(required <= configure.keys())
        self.assertTrue(required <= build)
        self.assertIn("hpm5321-flash-release-fs", configure)
        self.assertIn("hpm5321-flash-release-fs", build)
        self.assertIn("hpm5321-flash-release-500k-preflight", configure)
        self.assertIn("hpm5321-flash-release-500k-preflight", build)
        self.assertEqual(
            configure["hpm5321-flash-release-500k-preflight"]["cacheVariables"][
                "APP_MCAN_BITRATE"
            ],
            "500000",
        )
        self.assertEqual(
            configure["hpm5321-flash-release-fs"]["cacheVariables"][
                "APP_USB_FORCE_FULL_SPEED"
            ],
            "ON",
        )
        self.assertEqual(
            configure["hpm5321-base"]["cacheVariables"]["CMAKE_EXPORT_COMPILE_COMMANDS"],
            "ON",
        )

    def test_shared_development_config_has_no_personal_home(self):
        paths = [ROOT / "CMakePresets.json", ROOT / ".vscode", ROOT / "scripts/env"]
        files = [paths[0], *paths[1].glob("*.json"), *paths[2].glob("*")]
        for path in files:
            if path.is_file():
                self.assertNotIn("/home/gtc/", path.read_text(), str(path))

    def test_vscode_tasks_use_the_build_contract(self):
        tasks = json.loads((ROOT / ".vscode/tasks.json").read_text())["tasks"]
        self.assertEqual(len(tasks), 3)
        for task in tasks:
            self.assertEqual(task["command"], "${workspaceFolder}/scripts/build.sh")

    def test_linux_windows_cli_scope_locks_single_rust_core(self):
        workspace = (ROOT / "host/Cargo.toml").read_text()
        addendum = (ROOT / "docs/approved-plan/scope-addendum-linux-windows-cli.md").read_text()
        self.assertIn('"crates/usb-smoke"', workspace)
        self.assertIn('"spike/rust"', workspace)
        self.assertIn('unsafe_code = "forbid"', workspace)
        self.assertIn("shared host core and CLI use Rust", addendum)
        self.assertIn("macOS is deferred", addendum)
        self.assertIn("must not introduce a second protocol/USB core", addendum)

    def test_windows_collector_fails_closed_on_product_evidence(self):
        collector = (ROOT / "scripts/phase1/collect_windows_phase1b.ps1").read_text()
        for token in (
            "DEVPKEY_Device_Service",
            "DEVPKEY_Device_DriverProvider",
            "DEVPKEY_Device_DriverVersion",
            '$_.Service -ieq "WinUSB"',
            "Read-FirmwareProvenance",
            '$manifest.source_dirty -isnot [bool]',
            "Firmware manifest must record source_dirty=false",
            'foreach ($name in @("demo.elf", "demo.bin"))',
            "Firmware artifact does not match manifest",
            "DeviceAttested = $false",
            "Get-FileHash -Algorithm SHA256 $exe, $lock",
            "--bytes 67108864",
            "$ExerciseDisconnectRecovery",
            "DisconnectRecoveryExercised",
            "Compress-Archive",
        ):
            self.assertIn(token, collector)


if __name__ == "__main__":
    unittest.main()
