"""End-to-end check of the container runner without Docker or LabVIEW.

The NI container is stood in for by a fake ``subprocess.run`` that writes the
same plain-text log ``LabVIEWCLI -OperationName MassCompile`` produces and exits
with the same code, so the whole chain -- command construction, exit-code
handling, log parsing, capability result, report rendering -- is exercised as it
would be on a self-hosted Windows runner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fscicd.capabilities.mass_compile import run_mass_compile
from fscicd.config import Config, LabVIEWConfig, MassCompileConfig
from fscicd.labview import container as container_module
from fscicd.labview.container import ContainerRunner, ContainerRunnerError
from fscicd.models import Status
from fscicd.pipeline import run_pipeline

WINDOWS_IMAGE = "nationalinstruments/labview:2026q3-windows"

# Shaped after a real log captured from the NI Windows container (see
# tests/fixtures/masscompile_windows_2026.log): one file errors, one compiles,
# the rest are skipped, and the operation still reports success.
CONTAINER_LOG = (
    'Using LabVIEW: "C:\\Program Files\\National Instruments\\LabVIEW 2026\\LabVIEW.exe"\r\n'
    "LabVIEW launched successfully.\r\n"
    "Connection established with LabVIEW at port number 3363.\r\n"
    "\r\n"
    "Operation output: \r\n"
    "#### Starting Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
    '  Directory: "C:\\work"\r\n'
    "CompileFile: error 74 at C:\\work\\Signal Generator\\Broken Acquisition.vi\r\n"
    "CompileFile: compiling C:\\work\\Signal Generator\\Generate Sine.vi\r\n"
    "CompileFile: skipping C:\\work\\Utilities\\Loader.vi\r\n"
    "CompileFile: skipping C:\\work\\Utilities\\Clamp.vi\r\n"
    "#### Finished Mass Compile: Tue, Aug 18, 2026 10:25:41 AM\r\n"
    "\r\n"
    "MassCompile operation succeeded.\r\n"
)


def _host_side_of_out_mount(argv: list[str]) -> str:
    for suffix in (":C:\\out", ":/out"):
        for arg in argv:
            if arg.endswith(suffix):
                return arg[: -len(suffix)]
    raise AssertionError(f"no output mount in {argv!r}")


def _fake_container(monkeypatch, *, exit_code: int, log_text: str | None = CONTAINER_LOG):
    """Patch docker out, writing ``log_text`` where the container would."""

    monkeypatch.setattr(container_module.shutil, "which", lambda _name: "/usr/bin/docker")
    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(argv)
        if log_text is not None:
            # Translate the in-container log path back to the bind-mounted host
            # directory, which is what the real container writes through. A
            # Windows mount spec contains the drive-letter colon, so the
            # container half is stripped as a known suffix rather than by split.
            out_host = Path(_host_side_of_out_mount(argv))
            out_host.mkdir(parents=True, exist_ok=True)
            (out_host / "mass_compile.log").write_bytes(log_text.encode("utf-16"))
        return subprocess.CompletedProcess(argv, exit_code, stdout="", stderr="")

    monkeypatch.setattr(container_module.subprocess, "run", fake_run)
    return calls


@pytest.fixture
def labview_repo(tmp_path):
    """A minimal checkout with the VIs the fake log refers to."""

    (tmp_path / "Signal Generator").mkdir()
    (tmp_path / "Utilities").mkdir()
    for rel in (
        "Signal Generator/Broken Acquisition.vi",
        "Signal Generator/Generate Sine.vi",
        "Utilities/Loader.vi",
        "Utilities/Clamp.vi",
    ):
        (tmp_path / rel).write_text("stub VI")
    (tmp_path / "Demo.lvproj").write_text("stub project")
    return tmp_path


def test_windows_mass_compile_parses_container_log(monkeypatch, labview_repo):
    calls = _fake_container(monkeypatch, exit_code=3)
    runner = ContainerRunner(LabVIEWConfig(runner="container", image=WINDOWS_IMAGE), labview_repo)

    result = runner.mass_compile(["**/*.vi", "**/*.ctl"], ["**/*.lvproj"])

    # The invocation that would have reached Docker is Windows-shaped.
    argv = calls[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("-DirectoryToCompile") + 1] == "C:\\work"
    assert argv[argv.index("-LogFilePath") + 1] == "C:\\out\\mass_compile.log"
    assert "-Headless" in argv

    assert result.status is Status.FAILED
    assert result.total == 4
    assert result.broken == 1
    assert result.skipped == 2
    assert result.compiled == 1

    problem = result.vis[0]
    assert problem.path == "Signal Generator/Broken Acquisition.vi"
    assert problem.broken is True
    assert "error 74" in problem.message


def test_clean_container_run_passes(monkeypatch, labview_repo):
    clean_log = "Operation: MassCompile\r\nMass Compile completed.\r\n"
    _fake_container(monkeypatch, exit_code=0, log_text=clean_log)
    runner = ContainerRunner(LabVIEWConfig(runner="container", image=WINDOWS_IMAGE), labview_repo)

    result = runner.mass_compile(["**/*.vi"], ["**/*.lvproj"])

    assert result.status is Status.PASSED
    assert result.broken == 0
    assert result.total == 4


def test_timeout_is_reported_and_the_container_removed(monkeypatch, labview_repo):
    """A hanging LabVIEW operation must not occupy the runner indefinitely."""

    monkeypatch.setattr(container_module.shutil, "which", lambda _n: "/usr/bin/docker")
    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(argv)
        if argv[:3] == ["docker", "rm", "--force"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    monkeypatch.setattr(container_module.subprocess, "run", fake_run)
    config = LabVIEWConfig(runner="container", image=WINDOWS_IMAGE, timeout_minutes=5)
    runner = ContainerRunner(config, labview_repo)

    with pytest.raises(ContainerRunnerError) as excinfo:
        runner.mass_compile(["**/*.vi"], ["**/*.lvproj"])
    assert "timeout_minutes (5 min)" in str(excinfo.value)

    # The run was given the configured timeout, and the container it named was
    # then force-removed: killing the docker client alone leaves it running.
    assert calls[0][:3] == ["docker", "run", "--rm"]
    container_name = calls[0][calls[0].index("--name") + 1]
    assert container_name.startswith("fscicd-")
    assert calls[1] == ["docker", "rm", "--force", container_name]


def test_each_run_gets_a_unique_container_name(labview_repo):
    runner = ContainerRunner(LabVIEWConfig(runner="container", image=WINDOWS_IMAGE), labview_repo)
    first = runner.build_masscompile_command(labview_repo / "out")
    second = runner.build_masscompile_command(labview_repo / "out")
    assert first[first.index("--name") + 1] != second[second.index("--name") + 1]


def test_container_failure_exit_code_raises(monkeypatch, labview_repo):
    _fake_container(monkeypatch, exit_code=1, log_text=None)
    runner = ContainerRunner(LabVIEWConfig(runner="container", image=WINDOWS_IMAGE), labview_repo)

    with pytest.raises(ContainerRunnerError):
        runner.mass_compile(["**/*.vi"], ["**/*.lvproj"])


def test_capability_summarises_container_result(monkeypatch, labview_repo):
    _fake_container(monkeypatch, exit_code=3)
    runner = ContainerRunner(LabVIEWConfig(runner="container", image=WINDOWS_IMAGE), labview_repo)

    capability = run_mass_compile(runner, MassCompileConfig())

    assert capability.status is Status.FAILED
    # The summary has to state what was actually compiled: LabVIEW skipping
    # everything otherwise reads the same as a clean build.
    assert capability.summary == "1 of 4 files failed to compile (1 compiled, 2 skipped)."
    assert capability.details["skipped"] == 2


def test_pipeline_and_report_over_container_runner(monkeypatch, labview_repo, tmp_path):
    from fscicd.config import CapabilitiesConfig, UnitTestsConfig, ViAnalyzerConfig
    from fscicd.report import write_reports

    _fake_container(monkeypatch, exit_code=3)
    config = Config(
        project_name="Windows Container Demo",
        labview=LabVIEWConfig(runner="container", image=WINDOWS_IMAGE),
        capabilities=CapabilitiesConfig(
            mass_compile=MassCompileConfig(enabled=True),
            vi_analyzer=ViAnalyzerConfig(enabled=False),
            unit_tests=UnitTestsConfig(enabled=False),
        ),
    )

    result = run_pipeline(config, labview_repo, "abc123")
    assert result.status is Status.FAILED

    # Disabled capabilities are reported as skipped rather than omitted, so a
    # Windows run never tries to parse a report the operation did not write.
    by_name = {c.name: c for c in result.capabilities}
    assert by_name["Mass Compile"].status is Status.FAILED
    assert by_name["VI Analyzer"].status is Status.SKIPPED
    assert by_name["Unit Tests"].status is Status.SKIPPED

    paths = write_reports(result, tmp_path / "reports")
    html = paths["html"].read_text()
    assert "Broken Acquisition.vi" in html
    assert "error 74" in html
    assert "2 skipped" in html
