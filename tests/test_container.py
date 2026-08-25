from __future__ import annotations

from pathlib import Path

import pytest

from fscicd.config import ConfigError, LabVIEWConfig
from fscicd.labview.container import (
    ContainerRunner,
    ContainerRunnerError,
    parse_junit_report,
    parse_masscompile_log,
    parse_vianalyzer_report,
    read_report_text,
)
from fscicd.models import Status

WINDOWS_IMAGE = "nationalinstruments/labview:2026q3-windows"


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


def test_vianalyzer_requires_a_viancfg(tmp_path):
    """LabVIEWCLI rejects RunVIAnalyzer without -ConfigPath (error -350050)."""

    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    with pytest.raises(ContainerRunnerError) as excinfo:
        runner.build_vianalyzer_command(tmp_path / "out", "")
    assert ".viancfg" in str(excinfo.value)


def test_vianalyzer_config_discovered_from_the_checkout(tmp_path):
    (tmp_path / "Analysis").mkdir()
    (tmp_path / "Analysis" / "deep.viancfg").write_text("stub")
    (tmp_path / "project.viancfg").write_text("stub")

    runner = ContainerRunner(_windows_config(), tmp_path)
    cmd = runner.build_vianalyzer_command(tmp_path / "out", "")

    # The shallowest config wins, and it resolves inside the mounted checkout -
    # not the output directory, which nothing ever writes a config into.
    assert cmd[cmd.index("-ConfigPath") + 1] == "C:\\work\\project.viancfg"


def test_vianalyzer_config_discovery_skips_tooling_dirs(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "generated.viancfg").write_text("stub")

    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    with pytest.raises(ContainerRunnerError):
        runner.build_vianalyzer_command(tmp_path / "out", "")


def test_vianalyzer_relative_config_path_is_mapped_into_the_container(tmp_path):
    runner = ContainerRunner(_windows_config(), tmp_path)
    cmd = runner.build_vianalyzer_command(tmp_path / "out", "Analysis/checks.viancfg")
    assert cmd[cmd.index("-ConfigPath") + 1] == "C:\\work\\Analysis\\checks.viancfg"


def test_platform_inferred_from_image_tag():
    assert LabVIEWConfig(image=WINDOWS_IMAGE).platform == "windows"
    assert LabVIEWConfig(image="nationalinstruments/labview:2026q3-linux").platform == "linux"
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


def test_unit_tests_refuse_to_run_in_the_stock_image(tmp_path):
    """RunUnitTests fails with -350053 there: the UTF JUnit library is absent."""

    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    with pytest.raises(ContainerRunnerError) as excinfo:
        runner.unit_tests(["**/*Test*.vi"], ["caraya"])
    message = str(excinfo.value)
    assert "-350053" in message
    assert "VIPM" in message


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


REAL_LOG = Path(__file__).parent / "fixtures" / "masscompile_windows_2026.log"


def test_parse_real_windows_2026_log():
    """A captured log from the NI Windows container: 1 error, everything skipped.

    LabVIEW reports "MassCompile operation succeeded" here even though it errored
    on the project and compiled nothing, so a parser that trusts the operation
    verdict (or finds no markers) reports a false green.
    """

    result = parse_masscompile_log(REAL_LOG, exit_code=0, total_vis=12)

    assert result.status is Status.FAILED
    assert result.total == 13
    assert result.compiled == 0
    assert result.skipped == 12
    assert result.broken == 1

    problem = result.vis[0]
    assert problem.path == "Signal Generator.lvproj"
    assert problem.broken is True
    assert "error 74" in problem.message


def test_real_log_is_ascii_not_utf16():
    """Guards the encoding sniffing: this log has no BOM and no NULs."""

    raw = REAL_LOG.read_bytes()
    assert not raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    assert b"\x00" not in raw
    assert "CompileFile:" in read_report_text(REAL_LOG)


def test_compile_verbs_are_counted_separately(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(
        "#### Starting Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
        '  Directory: "C:\\work"\r\n'
        "CompileFile: compiling C:\\work\\A.vi\r\n"
        "CompileFile: skipping C:\\work\\B.vi\r\n"
        "CompileFile: error 6 at C:\\work\\C.vi\r\n"
        "#### Finished Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
        "MassCompile operation succeeded.\r\n"
    )
    result = parse_masscompile_log(log)
    assert (result.total, result.compiled, result.skipped, result.broken) == (3, 1, 1, 1)
    assert result.status is Status.FAILED


def test_all_skipped_is_not_a_failure(tmp_path):
    """LabVIEW does not say why it skipped, so a skip alone cannot fail the gate."""

    log = tmp_path / "mass_compile.log"
    log.write_text(
        "CompileFile: skipping C:\\work\\A.vi\r\n"
        "CompileFile: skipping C:\\work\\B.vi\r\n"
        "MassCompile operation succeeded.\r\n"
    )
    result = parse_masscompile_log(log)
    assert result.status is Status.PASSED
    assert (result.total, result.compiled, result.skipped) == (2, 0, 2)


def test_operation_failed_verdict_fails_the_run(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text("CompileFile: compiling C:\\work\\A.vi\r\nMassCompile operation failed.\r\n")
    assert parse_masscompile_log(log).status is Status.FAILED


def test_banner_lines_are_not_mistaken_for_bad_vi_markers(tmp_path):
    log = tmp_path / "mass_compile.log"
    log.write_text(
        "#### Starting Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
        "#### Finished Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
    )
    result = parse_masscompile_log(log, total_vis=4)
    assert result.vis == []
    assert result.broken == 0


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


REAL_VIA_REPORT = Path(__file__).parent / "fixtures" / "vi_analyzer_report_windows_2026.txt"


def test_parse_real_vianalyzer_report():
    """A captured RunVIAnalyzer report: tab-separated text, not HTML or JSON."""

    result = parse_vianalyzer_report(REAL_VIA_REPORT)

    assert result.status is Status.FAILED
    assert result.tested_vis == 1642
    assert result.tests_run == 1642
    assert result.passed_tests == 207
    assert result.failed_tests == 1435
    assert result.unloadable_vis == 0

    # The fixture is trimmed to four failing-VI blocks; the summary counts above
    # are the operation's own, so they still describe the full run.
    assert len(result.findings) == 4
    first = result.findings[0]
    assert first.vi_path == "_Code/Well/Well Messages/Write Tares Msg/Do.vi"
    assert first.test == "Broken VI"
    assert first.severity == "high"
    assert first.message == "This VI is broken."


def test_vianalyzer_report_summary_headings_are_not_findings(tmp_path):
    """'Failed Tests' is both a count and a section heading; only one is a finding."""

    report = tmp_path / "report.txt"
    report.write_text(
        "VI Analyzer Results\r\n\r\nResults\r\n"
        "VIs Analyzed\t10\r\nTotal Tests Run\t10\r\nPassed Tests\t9\r\n"
        "Failed Tests\t1\r\nSkipped Tests\t0\r\n\r\n"
        "Errors\r\nVI not loadable\t0\r\n\r\n"
        "Failed Tests (sorted by VI)\r\n\r\n"
        "Main.vi (C:\\work\\Main.vi)\r\nBroken VI\tThis VI is broken.\r\n\r\n"
        "Testing Errors\r\n\r\n(none)\r\n"
    )
    result = parse_vianalyzer_report(report)
    assert result.failed_tests == 1
    assert [(f.vi_path, f.test) for f in result.findings] == [("Main.vi", "Broken VI")]


def test_vianalyzer_unclassified_tests_default_to_medium(tmp_path):
    report = tmp_path / "report.txt"
    report.write_text(
        "Results\r\nVIs Analyzed\t1\r\n\r\nFailed Tests (sorted by VI)\r\n\r\n"
        "Main.vi (C:\\work\\Main.vi)\r\nCoercion Dots\tThere are coercion dots.\r\n"
    )
    finding = parse_vianalyzer_report(report).findings[0]
    assert finding.severity == "medium"
    assert finding.category == "Unclassified"


def test_vianalyzer_clean_report_passes(tmp_path):
    report = tmp_path / "report.txt"
    report.write_text(
        "Results\r\nVIs Analyzed\t12\r\nTotal Tests Run\t12\r\n"
        "Passed Tests\t12\r\nFailed Tests\t0\r\n\r\n"
        "Failed Tests (sorted by VI)\r\n\r\nTesting Errors\r\n\r\n(none)\r\n"
    )
    result = parse_vianalyzer_report(report)
    assert result.status is Status.PASSED
    assert result.findings == []
    assert result.tested_vis == 12


def test_vianalyzer_missing_report_raises(tmp_path):
    with pytest.raises(ContainerRunnerError):
        parse_vianalyzer_report(tmp_path / "nope.txt")


def test_vianalyzer_command_has_no_format_argument(tmp_path):
    """A format argument is not required, and the operation ignores the extension."""

    (tmp_path / "checks.viancfg").write_text("stub")
    runner = ContainerRunner(_windows_config(), tmp_path)
    cmd = runner.build_vianalyzer_command(tmp_path / "out", "")
    assert "-ReportType" not in cmd
    assert "-ReportSaveType" not in cmd
    assert cmd[cmd.index("-ReportPath") + 1] == "C:\\out\\vi_analyzer_report.txt"
