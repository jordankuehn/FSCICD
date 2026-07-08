"""Structured result models shared across capabilities and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    """Outcome of a capability or the overall pipeline."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

    @property
    def is_failure(self) -> bool:
        return self is Status.FAILED


@dataclass
class ViCompileResult:
    """Result of compiling a single VI/CTL."""

    path: str
    ok: bool
    broken: bool = False
    missing_dependencies: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class MassCompileResult:
    """Aggregated Mass Compile result."""

    status: Status
    total: int
    compiled: int
    broken: int
    vis: list[ViCompileResult] = field(default_factory=list)

    @property
    def broken_vis(self) -> list[ViCompileResult]:
        return [v for v in self.vis if v.broken]


@dataclass
class AnalyzerFinding:
    """A single VI Analyzer finding."""

    vi_path: str
    test: str
    category: str  # Style | Documentation | Performance | Correctness
    severity: str  # high | medium | low
    message: str


@dataclass
class ViAnalyzerResult:
    """Aggregated VI Analyzer result."""

    status: Status
    tested_vis: int
    findings: list[AnalyzerFinding] = field(default_factory=list)

    def count_by_severity(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


@dataclass
class TestCaseResult:
    """A single unit-test case outcome."""

    name: str
    classname: str
    status: str  # passed | failed | error | skipped
    duration: float = 0.0
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("passed", "skipped")


@dataclass
class UnitTestResult:
    """Aggregated unit-test result merged across frameworks."""

    status: Status
    framework: str
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    cases: list[TestCaseResult] = field(default_factory=list)

    @property
    def failing_cases(self) -> list[TestCaseResult]:
        return [c for c in self.cases if not c.ok]


@dataclass
class CapabilityResult:
    """Uniform wrapper describing one capability's outcome for reporting."""

    name: str
    status: Status
    summary: str
    details: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Top-level pipeline outcome aggregating every capability."""

    project_name: str
    commit: str
    capabilities: list[CapabilityResult] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if not self.capabilities:
            return Status.SKIPPED
        if any(c.status is Status.FAILED for c in self.capabilities):
            return Status.FAILED
        if all(c.status is Status.SKIPPED for c in self.capabilities):
            return Status.SKIPPED
        return Status.PASSED
