"""Deterministic LabVIEW simulator used for local development and testing.

The mock scans the repository for LabVIEW source files and produces stable,
reproducible results derived from each file's path. This lets the orchestration,
reporting and Bitbucket-integration layers run end-to-end with no LabVIEW
install. Conventions used to make demos meaningful:

* a VI whose name contains ``broken`` is reported as broken;
* a VI whose name contains ``missing`` is reported with a missing dependency;
* VI Analyzer findings are seeded from the file path so runs are repeatable.
"""

from __future__ import annotations

import hashlib

from fscicd.labview.base import LabVIEWRunner
from fscicd.models import (
    AnalyzerFinding,
    MassCompileResult,
    Status,
    ViAnalyzerResult,
    ViCompileResult,
)

_ANALYZER_TESTS = [
    ("Style", "medium", "Block Diagram Width", "Block diagram exceeds one screen width."),
    ("Documentation", "low", "VI Documentation", "VI description is empty."),
    ("Performance", "medium", "Coercion Dots", "Coercion dot found on a numeric wire."),
    ("Correctness", "high", "Error Cluster Wired", "Error cluster is not wired through a subVI."),
    ("Style", "low", "Icon Present", "VI uses the default connector pane icon."),
]


def _seed(path: str) -> int:
    return int(hashlib.sha256(path.encode()).hexdigest(), 16)


class MockRunner(LabVIEWRunner):
    """Simulates LabVIEW automation with deterministic, path-seeded output."""

    def mass_compile(self, vi_globs: list[str], project_globs: list[str]) -> MassCompileResult:
        vis = self.discover(vi_globs)
        results: list[ViCompileResult] = []
        for rel in vis:
            name = rel.name.lower()
            broken = "broken" in name
            missing = ["subvi_helper.vi"] if "missing" in name else []
            ok = not broken and not missing
            message = ""
            if broken:
                message = "VI is broken (unresolved wire / bad connection)."
            elif missing:
                message = "VI is missing a dependency."
            results.append(
                ViCompileResult(
                    path=str(rel),
                    ok=ok,
                    broken=broken,
                    missing_dependencies=missing,
                    message=message,
                )
            )
        broken_count = sum(1 for r in results if not r.ok)
        status = Status.FAILED if broken_count else (Status.PASSED if results else Status.SKIPPED)
        return MassCompileResult(
            status=status,
            total=len(results),
            compiled=len(results) - broken_count,
            broken=broken_count,
            vis=results,
        )

    def vi_analyzer(self, config_path: str) -> ViAnalyzerResult:
        vis = self.discover(["**/*.vi"])
        findings: list[AnalyzerFinding] = []
        for rel in vis:
            seed = _seed(str(rel))
            # Deterministically select 0-2 findings per VI from the test catalog.
            count = seed % 3
            for i in range(count):
                idx = (seed >> (i + 1)) % len(_ANALYZER_TESTS)
                category, severity, test, message = _ANALYZER_TESTS[idx]
                findings.append(
                    AnalyzerFinding(
                        vi_path=str(rel),
                        test=test,
                        category=category,
                        severity=severity,
                        message=message,
                    )
                )
        high = sum(1 for f in findings if f.severity == "high")
        status = Status.FAILED if high else (Status.PASSED if vis else Status.SKIPPED)
        return ViAnalyzerResult(status=status, tested_vis=len(vis), findings=findings)
