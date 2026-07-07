"""Real LabVIEW backend: runs the official headless NI LabVIEW container.

LabVIEW 2026 Q1+ supports a ``-Headless`` mode that runs ``LabVIEWCLI``
operations with **no license activation** for CI/CD workflows. This runner
mounts the checkout into ``nationalinstruments/labview:*`` and invokes
``LabVIEWCLI`` for Mass Compile and VI Analyzer, then parses the JSON reports
the worker writes to a mounted output directory.

Docker is not required to develop the rest of FSCICD; the mock runner covers
local testing. The command builders here are pure and unit-tested so the exact
invocation can be verified without a LabVIEW install.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from fscicd.labview.base import LabVIEWRunner
from fscicd.models import (
    AnalyzerFinding,
    MassCompileResult,
    Status,
    TestCaseResult,
    UnitTestResult,
    ViAnalyzerResult,
    ViCompileResult,
)

CONTAINER_WORKDIR = "/work"
CONTAINER_OUTDIR = "/out"


class ContainerRunnerError(RuntimeError):
    """Raised when the LabVIEW container cannot be executed."""


class ContainerRunner(LabVIEWRunner):
    """Executes LabVIEW automation inside the official NI Docker image."""

    def _base_docker_args(self, out_dir: Path) -> list[str]:
        args = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self.repo_path.resolve()}:{CONTAINER_WORKDIR}",
            "-v",
            f"{out_dir.resolve()}:{CONTAINER_OUTDIR}",
        ]
        if self.config.headless:
            args += ["-e", "LV_RTE_HEADLESS=1"]
        args.append(self.config.image)
        return args

    def build_masscompile_command(self, out_dir: Path) -> list[str]:
        """Return the full ``docker run ... LabVIEWCLI`` argv for Mass Compile."""

        cmd = self._base_docker_args(out_dir)
        cmd += [
            "LabVIEWCLI",
            "-OperationName",
            "MassCompile",
            "-DirectoryToCompile",
            CONTAINER_WORKDIR,
            "-LogFilePath",
            f"{CONTAINER_OUTDIR}/mass_compile.log",
        ]
        if self.config.headless:
            cmd.append("-Headless")
        return cmd

    def build_vianalyzer_command(self, out_dir: Path, config_path: str) -> list[str]:
        """Return the full ``docker run ... LabVIEWCLI`` argv for VI Analyzer."""

        cmd = self._base_docker_args(out_dir)
        cmd += [
            "LabVIEWCLI",
            "-OperationName",
            "RunVIAnalyzer",
            "-ConfigPath",
            config_path or f"{CONTAINER_WORKDIR}/.fscicd/vi-analyzer.viancfg",
            "-ReportPath",
            f"{CONTAINER_OUTDIR}/vi_analyzer.json",
            "-ReportType",
            "JSON",
        ]
        if self.config.headless:
            cmd.append("-Headless")
        return cmd

    def build_unittest_command(self, out_dir: Path, framework: str) -> list[str]:
        """Return the full ``docker run ... LabVIEWCLI`` argv for unit tests.

        Uses the RunUnitTests operation, which drives the configured framework
        (Caraya / VI Tester / NI UTF) headlessly and emits a JUnit XML report.
        """

        cmd = self._base_docker_args(out_dir)
        cmd += [
            "LabVIEWCLI",
            "-OperationName",
            "RunUnitTests",
            "-TestFramework",
            framework,
            "-ProjectPath",
            CONTAINER_WORKDIR,
            "-JUnitReportPath",
            f"{CONTAINER_OUTDIR}/unit_tests.xml",
        ]
        if self.config.headless:
            cmd.append("-Headless")
        return cmd

    def _run(self, argv: list[str]) -> None:
        if shutil.which("docker") is None:
            raise ContainerRunnerError(
                "docker executable not found; use runner: mock for local development "
                "or run on a host with Docker and the NI LabVIEW image available."
            )
        proc = subprocess.run(argv, capture_output=True, text=True)  # noqa: S603
        if proc.returncode != 0:
            raise ContainerRunnerError(
                f"LabVIEW container command failed ({proc.returncode}):\n{proc.stderr}"
            )

    def mass_compile(self, vi_globs: list[str], project_globs: list[str]) -> MassCompileResult:
        out_dir = self.repo_path / "build" / "labview-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        self._run(self.build_masscompile_command(out_dir))
        return parse_masscompile_report(out_dir / "mass_compile.json")

    def vi_analyzer(self, config_path: str) -> ViAnalyzerResult:
        out_dir = self.repo_path / "build" / "labview-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        self._run(self.build_vianalyzer_command(out_dir, config_path))
        return parse_vianalyzer_report(out_dir / "vi_analyzer.json")

    def unit_tests(self, test_globs: list[str], frameworks: list[str]) -> UnitTestResult:
        out_dir = self.repo_path / "build" / "labview-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        framework = frameworks[0] if frameworks else "caraya"
        self._run(self.build_unittest_command(out_dir, framework))
        return parse_junit_report(out_dir / "unit_tests.xml", framework)


def parse_masscompile_report(path: Path) -> MassCompileResult:
    """Parse the worker's Mass Compile JSON report into a structured result."""

    data = json.loads(Path(path).read_text())
    vis = [
        ViCompileResult(
            path=item["path"],
            ok=item.get("ok", True),
            broken=item.get("broken", False),
            missing_dependencies=item.get("missing_dependencies", []),
            message=item.get("message", ""),
        )
        for item in data.get("vis", [])
    ]
    broken = sum(1 for v in vis if not v.ok)
    status = Status.FAILED if broken else (Status.PASSED if vis else Status.SKIPPED)
    return MassCompileResult(
        status=status,
        total=len(vis),
        compiled=len(vis) - broken,
        broken=broken,
        vis=vis,
    )


def parse_vianalyzer_report(path: Path) -> ViAnalyzerResult:
    """Parse the worker's VI Analyzer JSON report into a structured result."""

    data = json.loads(Path(path).read_text())
    findings = [
        AnalyzerFinding(
            vi_path=item["vi_path"],
            test=item.get("test", ""),
            category=item.get("category", ""),
            severity=item.get("severity", "low"),
            message=item.get("message", ""),
        )
        for item in data.get("findings", [])
    ]
    high = sum(1 for f in findings if f.severity == "high")
    tested = data.get("tested_vis", len({f.vi_path for f in findings}))
    status = Status.FAILED if high else Status.PASSED
    return ViAnalyzerResult(status=status, tested_vis=tested, findings=findings)


def parse_junit_report(path: Path, framework: str) -> UnitTestResult:
    """Parse a JUnit XML report (as emitted by the worker) into a result."""

    root = ET.fromstring(Path(path).read_text())  # noqa: S314 - trusted CI output
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    cases: list[TestCaseResult] = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")
            if error is not None:
                status, message = "error", error.get("message", "")
            elif failure is not None:
                status, message = "failed", failure.get("message", "")
            elif skipped is not None:
                status, message = "skipped", skipped.get("message", "")
            else:
                status, message = "passed", ""
            cases.append(
                TestCaseResult(
                    name=tc.get("name", ""),
                    classname=tc.get("classname", ""),
                    status=status,
                    duration=float(tc.get("time", 0) or 0),
                    message=message,
                )
            )
    passed = sum(1 for c in cases if c.status == "passed")
    failed = sum(1 for c in cases if c.status == "failed")
    errors = sum(1 for c in cases if c.status == "error")
    skipped = sum(1 for c in cases if c.status == "skipped")
    status = Status.FAILED if (failed or errors) else Status.PASSED
    return UnitTestResult(
        status=status,
        framework=framework,
        total=len(cases),
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        cases=cases,
    )
