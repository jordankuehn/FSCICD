"""Pipeline orchestrator: run enabled capabilities and aggregate results."""

from __future__ import annotations

from pathlib import Path

from fscicd.capabilities.mass_compile import run_mass_compile
from fscicd.capabilities.unit_tests import run_unit_tests
from fscicd.capabilities.vi_analyzer import run_vi_analyzer
from fscicd.config import Config
from fscicd.labview import build_runner
from fscicd.models import CapabilityResult, PipelineResult, Status


def run_pipeline(config: Config, repo_path: str | Path, commit: str) -> PipelineResult:
    """Execute all enabled capabilities against ``repo_path`` at ``commit``."""

    runner = build_runner(config.labview, str(repo_path))
    capabilities: list[CapabilityResult] = []

    if config.capabilities.mass_compile.enabled:
        capabilities.append(run_mass_compile(runner, config.capabilities.mass_compile))
    else:
        capabilities.append(CapabilityResult("Mass Compile", Status.SKIPPED, "Disabled in config."))

    if config.capabilities.vi_analyzer.enabled:
        capabilities.append(run_vi_analyzer(runner, config.capabilities.vi_analyzer))
    else:
        capabilities.append(CapabilityResult("VI Analyzer", Status.SKIPPED, "Disabled in config."))

    if config.capabilities.unit_tests.enabled:
        capabilities.append(run_unit_tests(runner, config.capabilities.unit_tests))
    else:
        capabilities.append(CapabilityResult("Unit Tests", Status.SKIPPED, "Disabled in config."))

    return PipelineResult(
        project_name=config.project_name,
        commit=commit,
        capabilities=capabilities,
    )
