"""Unit Tests capability: run LabVIEW unit tests and merge results.

Drives the configured framework(s) — Caraya, VI Tester, NI Unit Test Framework —
headlessly and merges their outcomes into one report section.
"""

from __future__ import annotations

from fscicd.config import UnitTestsConfig
from fscicd.labview.base import LabVIEWRunner
from fscicd.models import CapabilityResult, Status


def run_unit_tests(runner: LabVIEWRunner, config: UnitTestsConfig) -> CapabilityResult:
    result = runner.unit_tests(config.test_globs, config.frameworks)

    if result.status is Status.SKIPPED:
        status = Status.SKIPPED
        summary = "No unit tests found."
    elif (result.failed or result.errors) and config.fail_on_failures:
        status = Status.FAILED
        summary = (
            f"{result.failed} failed, {result.errors} errors "
            f"of {result.total} tests ({result.framework})."
        )
    else:
        status = Status.PASSED
        summary = f"{result.passed} of {result.total} tests passed ({result.framework})."

    return CapabilityResult(
        name="Unit Tests",
        status=status,
        summary=summary,
        details={
            "framework": result.framework,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
            "skipped": result.skipped,
            "cases": [vars(c) for c in result.cases],
        },
    )
