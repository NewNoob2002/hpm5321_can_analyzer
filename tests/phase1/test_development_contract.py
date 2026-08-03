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


if __name__ == "__main__":
    unittest.main()
