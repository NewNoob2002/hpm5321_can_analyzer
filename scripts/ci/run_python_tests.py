#!/usr/bin/env python3
"""Run the P0 Python suite and reject every non-passing outcome."""

import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANITIZER_REQUIRED_ENV = "P0_REQUIRE_SANITIZERS"


@dataclass(frozen=True)
class PythonTestSummary:
    # total is unittest's testsRun: test methods whose execution started.
    # Fixture-level synthetic outcomes are counted below but are not testsRun.
    total: int
    passed: int
    failures: int
    errors: int
    skipped: int
    unexpected_successes: int
    expected_failures: int
    fixture_outcomes: int

    @property
    def accepted(self):
        return (
            self.total > 0
            and self.passed == self.total
            and self.failures == 0
            and self.errors == 0
            and self.skipped == 0
            and self.unexpected_successes == 0
            and self.expected_failures == 0
            and self.fixture_outcomes == 0
        )


class CountingTestResult(unittest.TextTestResult):
    """Record successful test methods without inferring them by subtraction."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes = 0

    def addSuccess(self, test):
        self.successes += 1
        super().addSuccess(test)


def summarize(result):
    recorded_outcomes = (
        result.successes
        + len(result.failures)
        + len(result.errors)
        + len(result.skipped)
        + len(result.unexpectedSuccesses)
        + len(result.expectedFailures)
    )
    return PythonTestSummary(
        total=result.testsRun,
        passed=result.successes,
        failures=len(result.failures),
        errors=len(result.errors),
        skipped=len(result.skipped),
        unexpected_successes=len(result.unexpectedSuccesses),
        expected_failures=len(result.expectedFailures),
        fixture_outcomes=max(0, recorded_outcomes - result.testsRun),
    )


def run_suite(suite, stream=None, verbosity=2):
    output = stream or sys.stderr
    result = unittest.TextTestRunner(
        stream=output, verbosity=verbosity, resultclass=CountingTestResult
    ).run(suite)
    summary = summarize(result)
    output.write(
        "P0 Python summary: "
        f"total={summary.total} passed={summary.passed} "
        f"failures={summary.failures} errors={summary.errors} "
        f"skipped={summary.skipped} "
        f"unexpected_successes={summary.unexpected_successes} "
        f"expected_failures={summary.expected_failures} "
        f"fixture_outcomes={summary.fixture_outcomes}\n"
    )
    if not summary.accepted:
        output.write(
            "FAIL P0 Python gate: at least one test must be discovered and "
            "every discovered test must pass; "
            "sanitizer unavailability is a test-infrastructure failure.\n"
        )
    return summary


def main():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ[SANITIZER_REQUIRED_ENV] = "1"
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / "tests"),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    return 0 if run_suite(suite).accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
