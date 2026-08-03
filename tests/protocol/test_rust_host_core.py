import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "host"


class RustHostCoreTests(unittest.TestCase):
    """Transport abstraction + fake-backend regression gate (scope addendum
    2026-08-03): the same flows the libusb backend will run on hardware."""

    def test_core_transport_and_fake_backend_pass(self):
        result = subprocess.run(
            ["cargo", "test", "-p", "hpm-usb-can-core"],
            cwd=HOST,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0, f"cargo test failed:\n{result.stderr}"
        )
        self.assertIn("0 failed", result.stdout)
        self.assertIn("15 passed", result.stdout)

    def test_core_clippy_is_clean(self):
        result = subprocess.run(
            ["cargo", "clippy", "-p", "hpm-usb-can-core", "--all-targets"],
            cwd=HOST,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0, f"clippy failed:\n{result.stderr}"
        )
        self.assertNotIn("warning:", result.stderr)
        self.assertNotIn("warning:", result.stdout)


if __name__ == "__main__":
    unittest.main()
