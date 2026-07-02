from __future__ import annotations

from fscicd.capabilities.mass_compile import run_mass_compile
from fscicd.capabilities.vi_analyzer import run_vi_analyzer
from fscicd.config import (
    Config,
    LabVIEWConfig,
    MassCompileConfig,
    ViAnalyzerConfig,
)
from fscicd.labview.mock import MockRunner
from fscicd.models import Status
from fscicd.pipeline import run_pipeline


def test_run_mass_compile_capability(sample_repo):
    runner = MockRunner(LabVIEWConfig(), sample_repo)
    cap = run_mass_compile(runner, MassCompileConfig())
    assert cap.name == "Mass Compile"
    assert cap.status is Status.PASSED
    assert cap.details["total"] == 3


def test_vi_analyzer_fail_on_severity_none_passes(broken_repo):
    runner = MockRunner(LabVIEWConfig(), broken_repo)
    cap = run_vi_analyzer(runner, ViAnalyzerConfig(fail_on_severity="none"))
    assert cap.status is Status.PASSED


def test_vi_analyzer_high_fails(broken_repo):
    runner = MockRunner(LabVIEWConfig(), broken_repo)
    cap = run_vi_analyzer(runner, ViAnalyzerConfig(fail_on_severity="high"))
    # broken_repo VIs deterministically include a high-severity finding
    assert cap.status is Status.FAILED


def test_pipeline_aggregates_status(broken_repo):
    cfg = Config(project_name="P", labview=LabVIEWConfig())
    result = run_pipeline(cfg, broken_repo, "abc")
    assert result.status is Status.FAILED
    assert {c.name for c in result.capabilities} == {"Mass Compile", "VI Analyzer"}


def test_pipeline_respects_disabled_capabilities(sample_repo):
    cfg = Config(
        project_name="P",
        labview=LabVIEWConfig(),
    )
    cfg.capabilities.vi_analyzer = ViAnalyzerConfig(enabled=False)
    result = run_pipeline(cfg, sample_repo, "abc")
    via = next(c for c in result.capabilities if c.name == "VI Analyzer")
    assert via.status is Status.SKIPPED
