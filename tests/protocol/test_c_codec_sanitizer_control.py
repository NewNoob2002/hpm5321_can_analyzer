import io
import os
import subprocess
import unittest
from unittest import mock

from tests.protocol import test_c_codec_parity as parity


class CCodecSanitizerControlTests(unittest.TestCase):
    def test_probe_inherits_environment_and_forces_leak_detection_off(self):
        compile_result = subprocess.CompletedProcess([], 0, "", "")
        run_result = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                    "P0_PROBE_SENTINEL": "preserved",
                },
            ),
            mock.patch.object(parity.shutil, "which", return_value=None),
            mock.patch.object(
                parity.subprocess, "run", side_effect=[compile_result, run_result]
            ) as run,
        ):
            parity.CCodecParityTests.cc = "/toolchain/gcc"
            capability = parity.CCodecParityTests._find_sanitizer_compiler()

        self.assertEqual(capability.compiler, "/toolchain/gcc")
        self.assertEqual(run.call_count, 2)
        probe_env = run.call_args_list[0].kwargs["env"]
        harness_env = run.call_args_list[1].kwargs["env"]
        self.assertIs(probe_env, harness_env)
        self.assertEqual(probe_env["ASAN_OPTIONS"], "halt_on_error=1:detect_leaks=0")
        self.assertEqual(probe_env["P0_PROBE_SENTINEL"], "preserved")

    def test_probe_falls_back_from_gcc_to_clang(self):
        def find_compiler(name):
            return {"gcc": "/toolchain/gcc", "clang": "/toolchain/clang"}.get(
                name
            )

        results = [
            subprocess.CompletedProcess([], 1, "", "GCC sanitizer link failed"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        with (
            mock.patch.object(parity.shutil, "which", side_effect=find_compiler),
            mock.patch.object(parity.subprocess, "run", side_effect=results),
        ):
            parity.CCodecParityTests.cc = "/toolchain/gcc"
            capability = parity.CCodecParityTests._find_sanitizer_compiler()

        self.assertEqual(capability.compiler, "/toolchain/clang")

    def _run_codec_suite(self, required):
        capability = parity.SanitizerCapability(None, "synthetic unavailable runtime")
        suite = unittest.TestSuite(
            parity.CCodecParityTests(name)
            for name in (
                "test_all_vectors_byte_parity",
                "test_sanitizer_build_stays_clean",
                "test_session_scenarios",
                "test_session_sanitizer_build_stays_clean",
            )
        )
        with (
            mock.patch.dict(
                os.environ, {parity.SANITIZER_REQUIRED_ENV: "1" if required else "0"}
            ),
            mock.patch.object(parity.shutil, "which", return_value="/toolchain/gcc"),
            mock.patch.object(
                parity.CCodecParityTests,
                "_find_sanitizer_compiler",
                return_value=capability,
            ),
            mock.patch.object(parity.CCodecParityTests, "_run_harness"),
            mock.patch.object(parity.CCodecParityTests, "_run_session_harness"),
        ):
            return unittest.TextTestRunner(stream=io.StringIO()).run(suite)

    def test_non_forced_unavailability_skips_only_sanitizer_tests(self):
        result = self._run_codec_suite(required=False)

        self.assertEqual(result.testsRun, 4)
        self.assertEqual(len(result.skipped), 2)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(len(result.errors), 0)

    def test_p0_forced_unavailability_fails_only_sanitizer_tests(self):
        result = self._run_codec_suite(required=True)

        self.assertEqual(result.testsRun, 4)
        self.assertEqual(len(result.skipped), 0)
        self.assertEqual(len(result.failures), 2)
        self.assertEqual(len(result.errors), 0)
        self.assertTrue(
            all(
                "test infrastructure unavailable" in traceback
                for _, traceback in result.failures
            )
        )

    def test_sanitizer_compile_and_runtime_errors_fail_the_harness(self):
        case = parity.CCodecParityTests("test_sanitizer_build_stays_clean")
        case.cc = "/toolchain/gcc"
        failures = (
            [
                subprocess.CompletedProcess(
                    [], 1, "", "undefined reference to `__asan_init'"
                )
            ],
            [
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess(
                    [], 1, "", "ERROR: AddressSanitizer: heap-buffer-overflow"
                ),
            ],
        )
        for results in failures:
            with self.subTest(results=len(results)), mock.patch.object(
                parity.subprocess, "run", side_effect=results
            ):
                with self.assertRaises(AssertionError):
                    case._run_harness(
                        parity.SANITIZER_FLAGS,
                        case.cc,
                        sanitizer=True,
                    )


if __name__ == "__main__":
    unittest.main()
