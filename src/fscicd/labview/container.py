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
from pathlib import Path

from fscicd.labview.base import LabVIEWRunner
from fscicd.models import (
    AnalyzerFinding,
    MassCompileResult,
    Status,
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
