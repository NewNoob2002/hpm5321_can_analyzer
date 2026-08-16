import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
CODECDIR = ROOT / "protocol" / "v1" / "c"
VECTORDIR = ROOT / "protocol" / "v1" / "0"
HARNESS = ROOT / "tests" / "protocol" / "ucan_vector_test.c"
SESSION_HARNESS = ROOT / "tests" / "protocol" / "ucan_session_test.c"
SANITIZER_FLAGS = ("-fsanitize=address,undefined", "-fno-omit-frame-pointer")
SANITIZER_REQUIRED_ENV = "P0_REQUIRE_SANITIZERS"


@dataclass(frozen=True)
class SanitizerCapability:
    compiler: Optional[str]
    reason: str

    @property
    def available(self):
        return self.compiler is not None


def sanitizer_subprocess_environment():
    """Return the inherited environment with leak detection disabled.

    LeakSanitizer requires ptrace support that is intentionally unavailable in
    some CI sandboxes. Preserve every other parent variable and ASan option,
    remove all existing detect_leaks assignments, then append the required
    value so the policy is deterministic.
    """

    env = os.environ.copy()
    options = [
        option
        for option in env.get("ASAN_OPTIONS", "").split(":")
        if option and not option.startswith("detect_leaks=")
    ]
    options.append("detect_leaks=0")
    env["ASAN_OPTIONS"] = ":".join(options)
    return env


def sanitizers_required():
    return os.environ.get(SANITIZER_REQUIRED_ENV, "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class CCodecParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = shutil.which(os.environ.get("CC", "")) or shutil.which("gcc")
        if cls.cc is None:
            raise unittest.SkipTest("C compiler not available")
        cls.sanitizer_capability = cls._find_sanitizer_compiler()

    @classmethod
    def _find_sanitizer_compiler(cls):
        candidates = [
            shutil.which(os.environ.get("SANITIZER_CC", "")),
            cls.cc,
            shutil.which("gcc"),
            shutil.which("clang"),
        ]
        env = sanitizer_subprocess_environment()
        failures = []
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "probe.c"
            binary = Path(tmp) / "probe"
            source.write_text("int main(void) { return 0; }\n", encoding="ascii")
            for compiler in dict.fromkeys(item for item in candidates if item):
                compiled = subprocess.run(
                    [compiler, *SANITIZER_FLAGS, str(source), "-o", str(binary)],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                if compiled.returncode != 0:
                    detail = compiled.stderr.strip() or compiled.stdout.strip()
                    failures.append(f"{compiler}: sanitizer compile failed: {detail}")
                    continue
                ran = subprocess.run(
                    [str(binary)], capture_output=True, text=True, env=env
                )
                if ran.returncode == 0:
                    return SanitizerCapability(compiler, "probe passed")
                detail = ran.stderr.strip() or ran.stdout.strip()
                failures.append(f"{compiler}: sanitizer probe failed: {detail}")
        if not failures:
            failures.append("no GCC or Clang candidate was found")
        return SanitizerCapability(None, "; ".join(failures))

    def _sanitizer_compiler(self):
        capability = self.sanitizer_capability
        if capability.available:
            return capability.compiler
        message = f"ASan/UBSan test infrastructure unavailable: {capability.reason}"
        if sanitizers_required():
            self.fail(message)
        self.skipTest(message)

    def _run_harness(self, extra_flags=(), compiler=None, sanitizer=False):
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
            env = (
                sanitizer_subprocess_environment()
                if sanitizer
                else os.environ.copy()
            )
            compiled = subprocess.run(cmd, capture_output=True, text=True, env=env)
            self.assertEqual(
                compiled.returncode, 0, f"compilation failed:\n{compiled.stderr}"
            )
            ran = subprocess.run(
                [str(binary), str(VECTORDIR)],
                capture_output=True,
                text=True,
                env=env,
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
            SANITIZER_FLAGS,
            self._sanitizer_compiler(),
            sanitizer=True,
        )

    def _run_session_harness(self, extra_flags=(), compiler=None, sanitizer=False):
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
            env = (
                sanitizer_subprocess_environment()
                if sanitizer
                else os.environ.copy()
            )
            compiled = subprocess.run(cmd, capture_output=True, text=True, env=env)
            self.assertEqual(
                compiled.returncode, 0, f"session compile failed:\n{compiled.stderr}"
            )
            ran = subprocess.run(
                [str(binary)],
                capture_output=True,
                text=True,
                env=env,
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
            SANITIZER_FLAGS,
            self._sanitizer_compiler(),
            sanitizer=True,
        )


if __name__ == "__main__":
    unittest.main()
