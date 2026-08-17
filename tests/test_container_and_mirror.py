from __future__ import annotations

import json

import pytest

from fscicd.config import ConfigError, LabVIEWConfig
from fscicd.labview.container import (
    ContainerRunner,
    ContainerRunnerError,
    parse_junit_report,
    parse_masscompile_log,
    parse_vianalyzer_report,
)
from fscicd.mirror import MirrorPlan, mirror
from fscicd.models import Status

WINDOWS_IMAGE = "nationalinstruments/labview:2026q1-windows"


def _windows_config() -> LabVIEWConfig:
    return LabVIEWConfig(runner="container", image=WINDOWS_IMAGE)


def test_masscompile_command_is_headless(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_masscompile_command(tmp_path / "out")
    assert cmd[0] == "docker"
    assert "LabVIEWCLI" in cmd
    assert "MassCompile" in cmd
    assert "-Headless" in cmd
    assert any("LV_RTE_HEADLESS=1" in part for part in cmd)


def test_vianalyzer_command_uses_config_path(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_vianalyzer_command(tmp_path / "out", "/work/my.viancfg")
    assert "RunVIAnalyzer" in cmd
    assert "/work/my.viancfg" in cmd
    assert "-Headless" in cmd


def test_platform_inferred_from_image_tag():
    assert LabVIEWConfig(image=WINDOWS_IMAGE).platform == "windows"
    assert LabVIEWConfig(image="nationalinstruments/labview:2026q1-linux").platform == "linux"
    assert LabVIEWConfig(image="nationalinstruments/labview:latest-windows").platform == "windows"


def test_explicit_platform_overrides_image_tag():
    config = LabVIEWConfig(image="nationalinstruments/labview:custom", platform="windows")
    assert config.platform == "windows"


def test_invalid_platform_rejected():
    with pytest.raises(ConfigError):
        LabVIEWConfig(platform="macos")


def test_windows_commands_use_windows_mounts_and_labview_path(tmp_path):
    runner = ContainerRunner(_windows_config(), tmp_path)
    cmd = runner.build_masscompile_command(tmp_path / "out")
    assert "-DirectoryToCompile" in cmd
    assert cmd[cmd.index("-DirectoryToCompile") + 1] == "C:\\work"
    assert cmd[cmd.index("-LogFilePath") + 1] == "C:\\out\\mass_compile.log"
    assert any(part.endswith(":C:\\work") for part in cmd)
    labview_path = cmd[cmd.index("-LabVIEWPath") + 1]
    assert labview_path == "C:\\Program Files\\National Instruments\\LabVIEW 2026\\LabVIEW.exe"


def test_linux_commands_omit_labview_path(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_masscompile_command(tmp_path / "out")
    assert "-LabVIEWPath" not in cmd
    assert cmd[cmd.index("-DirectoryToCompile") + 1] == "/work"
    assert cmd[cmd.index("-LogFilePath") + 1] == "/out/mass_compile.log"


def test_windows_unittest_and_analyzer_paths(tmp_path):
    runner = ContainerRunner(_windows_config(), tmp_path)
    unit = runner.build_unittest_command(tmp_path / "out", "caraya")
    assert unit[unit.index("-JUnitReportPath") + 1] == "C:\\out\\unit_tests.xml"
    assert unit[unit.index("-ProjectPath") + 1] == "C:\\work"
    analyzer = runner.build_vianalyzer_command(tmp_path / "out", "")
    assert analyzer[analyzer.index("-ReportPath") + 1] == "C:\\out\\vi_analyzer.json"


def test_unittest_command_is_headless(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_unittest_command(tmp_path / "out", "caraya")
    assert "RunUnitTests" in cmd
    assert "caraya" in cmd
    assert "-Headless" in cmd
    assert any("unit_tests.xml" in part for part in cmd)


def test_parse_junit_report(tmp_path):
    report = tmp_path / "unit_tests.xml"
    report.write_text(
        """<testsuites>
          <testsuite name="Caraya">
            <testcase classname="Tests/A" name="test_ok" time="0.1"/>
            <testcase classname="Tests/A" name="test_bad" time="0.2">
              <failure message="boom">assert</failure>
            </testcase>
            <testcase classname="Tests/A" name="test_skip"><skipped/></testcase>
          </testsuite>
        </testsuites>"""
    )
    result = parse_junit_report(report, "caraya")
    assert result.status is Status.FAILED
    assert result.total == 3
    assert result.passed == 1
    assert result.failed == 1
    assert result.skipped == 1


CLEAN_LOG = """LabVIEWCLI started logging in file: C:\\Temp\\lv.log
Operation: MassCompile
Compiling directory C:\\work
Mass Compile completed.
"""

PROBLEM_LOG = """LabVIEWCLI started logging in file: C:\\Temp\\lv.log
Operation: MassCompile
### Bad VI:
Path="C:\\work\\Signal Generator\\Broken Acquisition.vi"
Search failed to find "Missing Helper.vi"
Caller: "C:\\work\\Utilities\\Loader.vi"
Mass Compile completed with errors.
"""


def test_parse_masscompile_log_clean(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(CLEAN_LOG)
    result = parse_masscompile_log(log, exit_code=0, total_vis=12)
    assert result.status is Status.PASSED
    assert result.total == 12
    assert result.compiled == 12
    assert result.broken == 0
    assert result.vis == []


def test_parse_masscompile_log_reports_broken_and_missing(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(PROBLEM_LOG)
    result = parse_masscompile_log(log, exit_code=3, total_vis=10)
    assert result.status is Status.FAILED
    assert result.total == 10
    assert result.broken == 2
    assert result.compiled == 8

    by_path = {vi.path: vi for vi in result.vis}
    assert by_path["Signal Generator/Broken Acquisition.vi"].broken is True
    loader = by_path["Utilities/Loader.vi"]
    assert loader.broken is False
    assert loader.missing_dependencies == ["Missing Helper.vi"]


def test_parse_masscompile_log_handles_utf16(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_bytes(PROBLEM_LOG.encode("utf-16"))
    result = parse_masscompile_log(log, exit_code=3)
    assert result.broken == 2


def test_parse_masscompile_log_fails_on_unexpected_exit(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(CLEAN_LOG)
    result = parse_masscompile_log(log, exit_code=1, total_vis=5)
    assert result.status is Status.FAILED


def test_parse_masscompile_log_skips_when_nothing_compiled(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(CLEAN_LOG)
    result = parse_masscompile_log(log, exit_code=0, total_vis=0)
    assert result.status is Status.SKIPPED


def test_parse_masscompile_log_requires_a_log(tmp_path):
    with pytest.raises(ContainerRunnerError):
        parse_masscompile_log(tmp_path / "missing.log")


def test_parse_vianalyzer_report(tmp_path):
    report = tmp_path / "via.json"
    report.write_text(
        json.dumps(
            {
                "tested_vis": 1,
                "findings": [
                    {"vi_path": "A.vi", "test": "T", "category": "Style", "severity": "high"}
                ],
            }
        )
    )
    result = parse_vianalyzer_report(report)
    assert result.status is Status.FAILED
    assert result.tested_vis == 1


def test_mirror_dry_run_returns_commands():
    cmds = mirror("origin", "https://github.com/o/r.git", dry_run=True)
    assert ["git", "push", "--mirror", "https://github.com/o/r.git"] in cmds


def test_mirror_plan_commands():
    plan = MirrorPlan("origin", "https://github.com/o/r.git")
    assert plan.commands()[-1][1] == "push"
