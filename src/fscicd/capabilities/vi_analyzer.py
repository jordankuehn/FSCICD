"""VI Analyzer capability: NI static analysis for style/docs/perf/correctness."""

from __future__ import annotations

from fscicd.config import ViAnalyzerConfig
from fscicd.labview.base import LabVIEWRunner
from fscicd.models import CapabilityResult, Status

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def run_vi_analyzer(runner: LabVIEWRunner, config: ViAnalyzerConfig) -> CapabilityResult:
    result = runner.vi_analyzer(config.config_path)

    threshold = _SEVERITY_ORDER.get(config.fail_on_severity, 3)
    failing = [f for f in result.findings if _SEVERITY_ORDER.get(f.severity, 0) >= threshold]
    if result.tested_vis == 0:
        status = Status.SKIPPED
    elif failing and threshold > 0:
        status = Status.FAILED
    else:
        status = Status.PASSED

    if status is Status.SKIPPED:
        summary = "No VIs analyzed."
    else:
        summary = (
            f"{len(result.findings)} findings across {result.tested_vis} VIs "
            f"(high={result.count_by_severity('high')}, "
            f"medium={result.count_by_severity('medium')}, "
            f"low={result.count_by_severity('low')})."
        )
        # Only the container backend reports per-test counts; the mock does not.
        if result.tests_run:
            summary += f" {result.passed_tests} tests passed, {result.failed_tests} failed."
        if result.unloadable_vis:
            # Usually means the environment, not the code: VIs whose dependencies
            # are absent from the image cannot be analyzed meaningfully.
            summary += f" {result.unloadable_vis} VIs were unloadable."

    return CapabilityResult(
        name="VI Analyzer",
        status=status,
        summary=summary,
        details={
            "tested_vis": result.tested_vis,
            "tests_run": result.tests_run,
            "passed_tests": result.passed_tests,
            "failed_tests": result.failed_tests,
            "unloadable_vis": result.unloadable_vis,
            "fail_on_severity": config.fail_on_severity,
            "findings": [vars(f) for f in result.findings],
        },
    )
