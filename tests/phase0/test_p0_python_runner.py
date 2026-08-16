import io
import os
import sys
import types
import unittest
from unittest import mock

from scripts.ci import run_python_tests


class P0PythonRunnerTests(unittest.TestCase):
    def run_case(self, suite):
        stream = io.StringIO()
        summary = run_python_tests.run_suite(suite, stream=stream, verbosity=0)
        self.assertGreaterEqual(summary.passed, 0)
        return summary, stream.getvalue()

    def assert_rejected(self, suite, **counts):
        summary, output = self.run_case(suite)
        self.assertFalse(summary.accepted)
        for name, expected in counts.items():
            self.assertEqual(getattr(summary, name), expected, name)
        self.assertIn("FAIL P0 Python gate", output)
        return summary

    def test_all_passing_suite_is_accepted_without_fixed_test_count(self):
        class PassingTest(unittest.TestCase):
            def runTest(self):
                pass

        summary, output = self.run_case(
            unittest.TestSuite([PassingTest(), PassingTest(), PassingTest()])
        )
        self.assertTrue(summary.accepted)
        self.assertEqual((summary.total, summary.passed), (3, 3))
        self.assertEqual(summary.fixture_outcomes, 0)
        self.assertIn("total=3 passed=3", output)

    def test_empty_suite_is_rejected_without_negative_counts(self):
        summary = self.assert_rejected(
            unittest.TestSuite(), total=0, passed=0, fixture_outcomes=0
        )
        self.assertEqual((summary.total, summary.passed, summary.fixture_outcomes), (0, 0, 0))

    def test_method_skip_is_rejected(self):
        class Case(unittest.TestCase):
            @unittest.skip("skip")
            def runTest(self):
                pass
        self.assert_rejected(unittest.TestSuite([Case()]), total=1, passed=0, skipped=1)

    def test_method_failure_is_rejected(self):
        class Case(unittest.TestCase):
            def runTest(self):
                self.fail("failure")
        self.assert_rejected(unittest.TestSuite([Case()]), total=1, passed=0, failures=1)

    def test_method_error_is_rejected(self):
        class Case(unittest.TestCase):
            def runTest(self):
                raise RuntimeError("error")
        self.assert_rejected(unittest.TestSuite([Case()]), total=1, passed=0, errors=1)

    def test_expected_failure_is_rejected(self):
        class Case(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                self.fail("expected")
        self.assert_rejected(
            unittest.TestSuite([Case()]), total=1, passed=0, expected_failures=1
        )

    def test_unexpected_success_is_rejected(self):
        class Case(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                pass
        self.assert_rejected(
            unittest.TestSuite([Case()]), total=1, passed=0, unexpected_successes=1
        )

    def test_set_up_class_skip_is_a_fixture_outcome_not_a_negative_pass(self):
        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("fixture skip")
            def test_one(self):
                pass
        self.assert_rejected(
            unittest.defaultTestLoader.loadTestsFromTestCase(Case),
            total=0, passed=0, skipped=1, fixture_outcomes=1,
        )

    def test_set_up_class_error_is_a_fixture_outcome(self):
        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("fixture error")
            def test_one(self):
                pass
        self.assert_rejected(
            unittest.defaultTestLoader.loadTestsFromTestCase(Case),
            total=0, passed=0, errors=1, fixture_outcomes=1,
        )

    def module_suite(self, fixture):
        module = types.ModuleType(f"synthetic_{fixture.__name__}")
        module.setUpModule = fixture
        case = type(
            "ModuleCase",
            (unittest.TestCase,),
            {"__module__": module.__name__, "test_one": lambda self: None},
        )
        module.ModuleCase = case
        # unittest resolves module fixtures through sys.modules while the suite runs.
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        return unittest.defaultTestLoader.loadTestsFromModule(module)

    def test_set_up_module_skip_is_a_fixture_outcome(self):
        def fixture():
            raise unittest.SkipTest("module skip")
        self.assert_rejected(
            self.module_suite(fixture), total=0, passed=0, skipped=1, fixture_outcomes=1
        )

    def test_set_up_module_error_is_a_fixture_outcome(self):
        def fixture():
            raise RuntimeError("module error")
        self.assert_rejected(
            self.module_suite(fixture), total=0, passed=0, errors=1, fixture_outcomes=1
        )

    def test_main_enables_mandatory_sanitizer_mode(self):
        accepted = run_python_tests.PythonTestSummary(
            total=1, passed=1, failures=0, errors=0, skipped=0,
            unexpected_successes=0, expected_failures=0, fixture_outcomes=0,
        )

        def observe_required_mode(_suite):
            self.assertEqual(os.environ[run_python_tests.SANITIZER_REQUIRED_ENV], "1")
            return accepted

        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(
                run_python_tests.unittest.defaultTestLoader, "discover",
                return_value=unittest.TestSuite(),
            ),
            mock.patch.object(run_python_tests, "run_suite", side_effect=observe_required_mode),
        ):
            self.assertEqual(run_python_tests.main(), 0)

    def test_main_rejects_empty_discovery(self):
        with mock.patch.object(
            run_python_tests.unittest.defaultTestLoader,
            "discover",
            return_value=unittest.TestSuite(),
        ):
            self.assertEqual(run_python_tests.main(), 1)


if __name__ == "__main__":
    unittest.main()
