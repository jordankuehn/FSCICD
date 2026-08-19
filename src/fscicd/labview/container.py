"""Real LabVIEW backend: runs the official headless NI LabVIEW container.

LabVIEW 2026 Q1+ supports a ``-Headless`` mode that runs ``LabVIEWCLI``
operations with **no license activation** for CI/CD workflows. This runner
mounts the checkout into ``nationalinstruments/labview:*`` and invokes
``LabVIEWCLI``, then parses the reports the operation leaves in a mounted
output directory.

Mass Compile has no machine-readable output: ``LabVIEWCLI`` writes a plain-text
log, so :func:`parse_masscompile_log` reads the markers LabVIEW emits for VIs it
could not load and for subVIs it could not resolve.

Docker is not required to develop the rest of FSCICD; the mock runner covers
local testing. The command builders here are pure and unit-tested so the exact
invocation can be verified without a LabVIEW install.
"""

from __future__ import annotations

import codecs
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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

# MassCompile returns 3 when it finished but flagged some VIs as bad. That is a
# reportable outcome, not a runner failure, so the log still gets parsed.
MASSCOMPILE_PARTIAL_EXIT = 3

# Directories that hold tooling or build output rather than project source, and
# so must not supply a discovered VI Analyzer configuration.
_NON_PROJECT_DIRS = frozenset({".git", ".venv", ".cursor", "build", "ci-out", "dist"})


@dataclass(frozen=True)
class ContainerPaths:
    """In-container mount points and LabVIEW location for one platform."""

    workdir: str
    outdir: str
    labview_path: str

    def out(self, name: str) -> str:
        sep = "\\" if "\\" in self.outdir else "/"
        return f"{self.outdir}{sep}{name}"


def container_paths(platform: str, version: str) -> ContainerPaths:
    """Return the mount layout for a Windows or Linux NI LabVIEW image."""

    if platform == "windows":
        return ContainerPaths(
            workdir="C:\\work",
            outdir="C:\\out",
            labview_path=(
                f"C:\\Program Files\\National Instruments\\LabVIEW {version}\\LabVIEW.exe"
            ),
        )
    # The Linux images install under a versioned /usr/local/natinst path that
    # varies by tag, so let LabVIEWCLI resolve the executable itself.
    return ContainerPaths(workdir="/work", outdir="/out", labview_path="")


class ContainerRunnerError(RuntimeError):
    """Raised when the LabVIEW container cannot be executed."""


class ContainerRunner(LabVIEWRunner):
    """Executes LabVIEW automation inside the official NI Docker image."""

    @property
    def paths(self) -> ContainerPaths:
        return container_paths(self.config.platform, self.config.version)

    def _base_docker_args(self, out_dir: Path) -> list[str]:
        paths = self.paths
        args = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self.repo_path.resolve()}:{paths.workdir}",
            "-v",
            f"{out_dir.resolve()}:{paths.outdir}",
        ]
        if self.config.headless:
            args += ["-e", "LV_RTE_HEADLESS=1"]
        args.append(self.config.image)
        return args

    def _labview_path_args(self) -> list[str]:
        path = self.paths.labview_path
        return ["-LabVIEWPath", path] if path else []

    def build_masscompile_command(self, out_dir: Path) -> list[str]:
        """Return the full ``docker run ... LabVIEWCLI`` argv for Mass Compile."""

        paths = self.paths
        cmd = self._base_docker_args(out_dir)
        cmd += [
            "LabVIEWCLI",
            "-OperationName",
            "MassCompile",
            "-DirectoryToCompile",
            paths.workdir,
            "-LogFilePath",
            paths.out("mass_compile.log"),
        ]
        cmd += self._labview_path_args()
        if self.config.headless:
            cmd.append("-Headless")
        return cmd

    def _in_container(self, repo_relative: str) -> str:
        """Map a repo-relative path to where the checkout is mounted."""

        paths = self.paths
        sep = "\\" if "\\" in paths.workdir else "/"
        cleaned = repo_relative.replace("\\", "/").strip().lstrip("/")
        return f"{paths.workdir}{sep}{cleaned.replace('/', sep)}"

    def discover_vianalyzer_config(self) -> str | None:
        """Return the repo-relative path of a committed ``.viancfg``, if any.

        The shallowest wins, so a configuration at the project root takes
        precedence over one buried in a subdirectory.
        """

        candidates = []
        for match in self.repo_path.rglob("*.viancfg"):
            rel = match.relative_to(self.repo_path)
            if any(part in _NON_PROJECT_DIRS for part in rel.parts):
                continue
            candidates.append(rel)
        if not candidates:
            return None
        candidates.sort(key=lambda rel: (len(rel.parts), str(rel)))
        return candidates[0].as_posix()

    def _config_path_arg(self, config_path: str) -> str:
        """Resolve the ``-ConfigPath`` value, which LabVIEWCLI requires."""

        resolved = config_path.strip() or self.discover_vianalyzer_config()
        if not resolved:
            raise ContainerRunnerError(
                "VI Analyzer needs a .viancfg: LabVIEWCLI rejects RunVIAnalyzer "
                "without -ConfigPath (error -350050). Author a VI Analyzer "
                "configuration in the LabVIEW IDE, commit it to the repository, and "
                "either leave capabilities.vi_analyzer.config_path empty to use the "
                "first .viancfg found in the checkout or point it at a specific one."
            )
        # An already-absolute path is assumed to be container-side and passed
        # through; anything else is relative to the mounted checkout.
        if resolved.startswith(("/", "C:\\", "c:\\", "C:/", "c:/")):
            return resolved
        return self._in_container(resolved)

    def build_vianalyzer_command(self, out_dir: Path, config_path: str) -> list[str]:
        """Return the full ``docker run ... LabVIEWCLI`` argv for VI Analyzer."""

        paths = self.paths
        cmd = self._base_docker_args(out_dir)
        cmd += [
            "LabVIEWCLI",
            "-OperationName",
            "RunVIAnalyzer",
            "-ConfigPath",
            self._config_path_arg(config_path),
            "-ReportPath",
            paths.out("vi_analyzer.json"),
            "-ReportType",
            "JSON",
        ]
        cmd += self._labview_path_args()
        if self.config.headless:
            cmd.append("-Headless")
        return cmd

    def _run(self, argv: list[str], ok_codes: tuple[int, ...] = (0,)) -> int:
        if shutil.which("docker") is None:
            raise ContainerRunnerError(
                "docker executable not found; use runner: mock for local development "
                "or run on a host with Docker and the NI LabVIEW image available."
            )
        proc = subprocess.run(argv, capture_output=True, text=True)  # noqa: S603
        if proc.returncode not in ok_codes:
            raise ContainerRunnerError(
                f"LabVIEW container command failed ({proc.returncode}):\n{proc.stderr}"
            )
        return proc.returncode

    def _out_dir(self) -> Path:
        out_dir = self.repo_path / "build" / "labview-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def mass_compile(self, vi_globs: list[str], project_globs: list[str]) -> MassCompileResult:
        out_dir = self._out_dir()
        exit_code = self._run(
            self.build_masscompile_command(out_dir),
            ok_codes=(0, MASSCOMPILE_PARTIAL_EXIT),
        )
        return parse_masscompile_log(
            out_dir / "mass_compile.log",
            exit_code=exit_code,
            total_vis=len(self.discover(vi_globs)),
        )

    def vi_analyzer(self, config_path: str) -> ViAnalyzerResult:
        out_dir = self._out_dir()
        self._run(self.build_vianalyzer_command(out_dir, config_path))
        return parse_vianalyzer_report(out_dir / "vi_analyzer.json")

    def unit_tests(self, test_globs: list[str], frameworks: list[str]) -> UnitTestResult:
        raise ContainerRunnerError(
            "Unit tests cannot run in the stock NI LabVIEW image. LabVIEWCLI's "
            "RunUnitTests operation fails with -350053 there because the UTF "
            "JUnit Report library is not installed, and Caraya and VI Tester are "
            "VIPM packages rather than CLI operations. Running them needs a worker "
            "image with those packages baked in via VIPM, which FSCICD does not "
            "build yet; keep capabilities.unit_tests disabled for container runs "
            "and use runner: mock for development."
        )


# LabVIEW 2026 reports one line per file it considered, e.g.
#
#     CompileFile: error 74 at C:\work\Signal Generator.lvproj
#     CompileFile: skipping C:\work\Signal Generator\Apply Window.vi
#
# See tests/fixtures/masscompile_windows_2026.log for a captured log.
_COMPILE_ERROR_RE = re.compile(
    r"^\s*CompileFile:\s+error\s+(?P<code>-?\d+)\s+at\s+(?P<path>.+?)\s*$",
    re.IGNORECASE,
)
_COMPILE_SKIP_RE = re.compile(r"^\s*CompileFile:\s+skipping\s+(?P<path>.+?)\s*$", re.IGNORECASE)
_COMPILE_OTHER_RE = re.compile(
    r"^\s*CompileFile:\s+(?P<verb>\S+)\s+(?P<path>.+?)\s*$", re.IGNORECASE
)

# The operation's own verdict. It reports success even when individual files
# errored, so it is a signal rather than the whole answer.
_OPERATION_RESULT_RE = re.compile(
    r"^\s*MassCompile operation\s+(?P<outcome>succeeded|failed)", re.IGNORECASE
)

# Additional markers seen in other LabVIEW log variants. Not observed in the
# 2026 container output, kept because they cost nothing and are specific enough
# not to collide with the "#### Starting Mass Compile" banners.
_BAD_VI_RE = re.compile(r"#+\s*Bad VI\s*:?\s*(?P<name>.*)", re.IGNORECASE)
_PATH_RE = re.compile(r'Path\s*=\s*"(?P<path>[^"]+)"')
_SEARCH_FAILED_RE = re.compile(r'Search failed to find\s+"(?P<missing>[^"]+)"', re.IGNORECASE)
_CALLER_RE = re.compile(r'Caller\s*:?\s*"(?P<caller>[^"]+)"')

_MARKER_WINDOW = 3
_BROKEN_MESSAGE = "LabVIEW flagged the VI as bad; it could not load or compile here."
_MISSING_MESSAGE = "A subVI or dependency could not be found in this container."


def read_masscompile_log(path: Path) -> str:
    """Read a MassCompile log, which LabVIEW may write as UTF-16.

    The encoding is chosen from the bytes rather than by trial decoding: ASCII
    decodes "successfully" as UTF-16 into mojibake, which would silently hide
    every marker in the log.
    """

    raw = Path(path).read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    if b"\x00" in raw:
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _to_repo_relative(path: str) -> str:
    """Normalise an in-container VI path to a repo-relative one."""

    normalised = path.replace("\\", "/").strip()
    for mount in ("c:/work/", "/work/"):
        if normalised.lower().startswith(mount):
            return normalised[len(mount) :]
    return normalised.lstrip("/")


def parse_masscompile_log(
    path: Path,
    *,
    exit_code: int = 0,
    total_vis: int | None = None,
) -> MassCompileResult:
    """Parse a ``LabVIEWCLI -OperationName MassCompile`` log into a result.

    The log is the only output the operation produces. It reports one
    ``CompileFile:`` line per file considered, and its own
    ``MassCompile operation succeeded`` verdict is not trustworthy on its own:
    LabVIEW reports success even when individual files errored.

    ``total_vis`` is the number of VIs the pipeline expected to compile, counted
    from the checkout, and is used only when the log names no files at all.
    """

    log_path = Path(path)
    if not log_path.is_file():
        raise ContainerRunnerError(
            f"Mass Compile log not found at {log_path}; the container produced no log."
        )

    lines = read_masscompile_log(log_path).splitlines()
    problems: dict[str, ViCompileResult] = {}
    seen: set[str] = set()
    skipped: set[str] = set()
    operation_failed = False

    def problem_for(vi_path: str) -> ViCompileResult:
        rel = _to_repo_relative(vi_path)
        if rel not in problems:
            problems[rel] = ViCompileResult(path=rel, ok=True)
        return problems[rel]

    for index, line in enumerate(lines):
        outcome = _OPERATION_RESULT_RE.match(line)
        if outcome:
            operation_failed = outcome.group("outcome").lower() == "failed"
            continue

        error = _COMPILE_ERROR_RE.match(line)
        if error:
            rel = _to_repo_relative(error.group("path"))
            seen.add(rel)
            vi = problem_for(error.group("path"))
            vi.ok = False
            vi.broken = True
            vi.message = f"LabVIEW error {error.group('code')} while compiling this file."
            continue

        skip = _COMPILE_SKIP_RE.match(line)
        if skip:
            rel = _to_repo_relative(skip.group("path"))
            seen.add(rel)
            skipped.add(rel)
            continue

        other = _COMPILE_OTHER_RE.match(line)
        if other:
            seen.add(_to_repo_relative(other.group("path")))
            continue

        # LabVIEW hard-wraps the log, so a marker's details can land on the next
        # line or two; match against a small window rather than a single line.
        window = " ".join(lines[index : index + _MARKER_WINDOW])

        bad_vi = _BAD_VI_RE.search(line)
        if bad_vi:
            quoted = _PATH_RE.search(window)
            name = quoted.group("path") if quoted else bad_vi.group("name").strip().strip('"')
            if name:
                seen.add(_to_repo_relative(name))
                vi = problem_for(name)
                vi.ok = False
                vi.broken = True
                vi.message = vi.message or _BROKEN_MESSAGE
            continue

        search_failed = _SEARCH_FAILED_RE.search(line)
        if search_failed:
            caller = _CALLER_RE.search(window)
            if caller:
                seen.add(_to_repo_relative(caller.group("caller")))
                vi = problem_for(caller.group("caller"))
                vi.ok = False
                missing = search_failed.group("missing").strip()
                if missing not in vi.missing_dependencies:
                    vi.missing_dependencies.append(missing)
                vi.message = vi.message or _MISSING_MESSAGE

    # Only problem files are listed individually; a real project skips thousands
    # of already-current VIs and listing them would drown the report.
    vis = [problems[key] for key in sorted(problems)]
    broken = sum(1 for v in vis if not v.ok)
    # Both are lower bounds on the number of files considered: the CompileFile
    # format enumerates every file, while the marker-only variants name just the
    # problems, so the checkout's own VI count is the better denominator there.
    total = max(len(seen), total_vis or 0, len(vis))
    skipped_count = len(skipped - set(problems))
    compiled = max(total - broken - skipped_count, 0)

    if broken or operation_failed or exit_code not in (0, MASSCOMPILE_PARTIAL_EXIT):
        status = Status.FAILED
    elif total:
        status = Status.PASSED
    else:
        status = Status.SKIPPED

    return MassCompileResult(
        status=status,
        total=total,
        compiled=compiled,
        broken=broken,
        skipped=skipped_count,
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
