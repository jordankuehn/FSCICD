from __future__ import annotations

from fscicd.config import LabVIEWConfig
from fscicd.labview.mock import MockRunner
from fscicd.models import Status


def test_mass_compile_clean(sample_repo):
    runner = MockRunner(LabVIEWConfig(runner="mock"), sample_repo)
    result = runner.mass_compile(["**/*.vi", "**/*.ctl"], ["**/*.lvproj"])
    assert result.status is Status.PASSED
    assert result.total == 3
    assert result.broken == 0


def test_mass_compile_detects_broken_and_missing(broken_repo):
    runner = MockRunner(LabVIEWConfig(runner="mock"), broken_repo)
    result = runner.mass_compile(["**/*.vi"], ["**/*.lvproj"])
    assert result.status is Status.FAILED
    assert result.broken == 2
    broken_names = {v.path for v in result.broken_vis}
    assert any("Broken" in n for n in broken_names)
    assert any(v.missing_dependencies for v in result.vis)


def test_mass_compile_empty_is_skipped(tmp_path):
    runner = MockRunner(LabVIEWConfig(runner="mock"), tmp_path)
    result = runner.mass_compile(["**/*.vi"], ["**/*.lvproj"])
    assert result.status is Status.SKIPPED
    assert result.total == 0


def test_vi_analyzer_is_deterministic(sample_repo):
    runner = MockRunner(LabVIEWConfig(runner="mock"), sample_repo)
    first = runner.vi_analyzer("")
    second = runner.vi_analyzer("")
    assert [vars(f) for f in first.findings] == [vars(f) for f in second.findings]
    assert first.tested_vis == 2  # only .vi files, not .ctl
