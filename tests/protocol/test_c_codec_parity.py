import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODECDIR = ROOT / "protocol" / "v1" / "c"
VECTORDIR = ROOT / "protocol" / "v1" / "0"
HARNESS = ROOT / "tests" / "protocol" / "ucan_vector_test.c"
SESSION_HARNESS = ROOT / "tests" / "protocol" / "ucan_session_test.c"


class CCodecParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = shutil.which(os.environ.get("CC", "")) or shutil.which("gcc")
        if cls.cc is None:
            raise unittest.SkipTest("C compiler not available")
        cls.sanitizer_cc = cls._find_sanitizer_compiler()

    @classmethod
    def _find_sanitizer_compiler(cls):
        candidates = [
            shutil.which(os.environ.get("SANITIZER_CC", "")),
            cls.cc,
            shutil.which("clang"),
        ]
        flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "probe.c"
            binary = Path(tmp) / "probe"
            source.write_text("int main(void) { return 0; }\n", encoding="ascii")
            for compiler in dict.fromkeys(item for item in candidates if item):
                result = subprocess.run(
                    [compiler, *flags, str(source), "-o", str(binary)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and subprocess.run(
                    [str(binary)], capture_output=True, text=True
                ).returncode == 0:
                    return compiler
        raise unittest.SkipTest("no C compiler with working ASan/UBSan runtime")

    def _run_harness(self, extra_flags=(), compiler=None):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "ucan_vector_test"
            sources = [str(HARNESS), str(CODECDIR / "ucan_codec.c")]
            cmd = [
                compiler or self.cc,
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                f"-I{CODECDIR}",
                *extra_flags,
                *sources,
                "-o",
                str(binary),
            ]
            compiled = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                compiled.returncode, 0, f"compilation failed:\n{compiled.stderr}"
            )
            ran = subprocess.run(
                [str(binary), str(VECTORDIR)],
                capture_output=True,
                text=True,
                env={"ASAN_OPTIONS": "detect_leaks=0", "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(
                ran.returncode,
                0,
                f"harness failed:\nstdout={ran.stdout}\nstderr={ran.stderr}",
            )
            self.assertIn("0 failures", ran.stdout)

    def test_all_vectors_byte_parity(self):
        self.assertEqual(len(list(VECTORDIR.glob("*.hex"))), 38)
        self._run_harness()

    def test_sanitizer_build_stays_clean(self):
        self._run_harness(
            ("-fsanitize=address,undefined", "-fno-omit-frame-pointer"),
            self.sanitizer_cc,
        )

    def _run_session_harness(self, extra_flags=(), compiler=None):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "ucan_session_test"
            cmd = [
                compiler or self.cc,
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                f"-I{CODECDIR}",
                *extra_flags,
                str(SESSION_HARNESS),
                str(CODECDIR / "ucan_session.c"),
                str(CODECDIR / "ucan_codec.c"),
                "-o",
                str(binary),
            ]
            compiled = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                compiled.returncode, 0, f"session compile failed:\n{compiled.stderr}"
            )
            ran = subprocess.run(
                [str(binary)],
                capture_output=True,
                text=True,
                env={"ASAN_OPTIONS": "detect_leaks=0", "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(
                ran.returncode,
                0,
                f"session harness failed:\nstdout={ran.stdout}\nstderr={ran.stderr}",
            )
            self.assertIn("0 failures", ran.stdout)

    def test_session_scenarios(self):
        self._run_session_harness()

    def test_session_sanitizer_build_stays_clean(self):
        self._run_session_harness(
            ("-fsanitize=address,undefined", "-fno-omit-frame-pointer"),
            self.sanitizer_cc,
        )


if __name__ == "__main__":
    unittest.main()
