# AGENTS.md

FSCICD is a **CI/CD system for LabVIEW code**. It runs Mass Compile and VI
Analyzer inside NI's official **headless LabVIEW containers**, renders an
HTML/JSON report, and posts a **Bitbucket** commit build status.

**Bitbucket is the code of record and the CI host.** CI is
`bitbucket-pipelines.yml`, and real LabVIEW jobs run on a **self-hosted Bitbucket
Windows runner** (labels `self.hosted`, `windows`, `labview`) because Atlassian
hosts no Windows runners and the projects target Windows. The old Bitbucket →
GitHub mirror and the GitHub Actions workflow are both deleted — do not
reintroduce either.

**But cloud agents currently work on the GitHub copy** at
`github.com/jordankuehn/FSCICD`, because connecting Cursor to Bitbucket Cloud
fails on a known bug in that integration (OAuth is granted on the Bitbucket side
but Cursor never reaches the "Connected" state). So:

- Push branches and open pull requests on **GitHub**, as normal.
- The owner replays merged `main` onto Bitbucket by hand
  (`git pull github main` then `git push origin main` in a clone where `origin`
  is Bitbucket). Nothing automated does this, and **CI does not run on GitHub**,
  so a change is untested by Pipelines until that replay happens.
- Do not re-add a mirror or a GitHub Actions workflow to paper over this; it is a
  temporary workaround for an upstream bug, not the intended architecture.

Key packages:
- `src/fscicd/` — Python package. Entry point CLI is `fscicd` (see `cli.py`).
- `src/fscicd/labview/` — pluggable LabVIEW backends: `mock` (deterministic
  simulator, no LabVIEW needed) and `container` (real, `docker run` the NI image).
- `bitbucket-pipelines.yml` — this repo's CI (cloud self-test + Windows LabVIEW
  step); `examples/bitbucket-pipelines.app-repo.yml` is the template LabVIEW
  application repos copy.
- `docker/labview-worker.Dockerfile` — Linux worker on the NI headless image.

## Cursor Cloud specific instructions

- **The environment is defined in `.cursor/environment.json`**, which Cursor
  resolves ahead of any saved dashboard environment. A clean checkout plus that
  one install command is enough, so an agent needs no dashboard setup whichever
  remote it is started from.
- **Python dev env lives in `.venv`.** After the update script runs, use
  `.venv/bin/<tool>` (e.g. `.venv/bin/pytest`, `.venv/bin/ruff`) or activate the
  venv. The package is installed editable, so `src/fscicd` edits take effect
  without reinstalling.
- **Standard commands** (all from repo root):
  - Lint: `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  - Tests: `.venv/bin/pytest`
  - YAML lint (CI configs): `.venv/bin/yamllint bitbucket-pipelines.yml examples`
  - Run the app (mock): `.venv/bin/fscicd run --config examples/fscicd.yml --repo-path "examples/sample-labview-project" --commit demo`
- **LabVIEW cannot run in this VM.** There is no NI license/Docker image here, and
  the images are Windows/Linux multi-GB LabVIEW installs. Develop and test with
  `runner: mock` in `fscicd.yml`. The `container` runner's command construction is
  unit-tested, but real `docker run` execution only happens on a CI runner with
  Docker + the NI headless image. Do not treat "cannot run LabVIEW here" as a bug.
- **Everything is LabVIEW 2026 64-bit.** There is no support for older versions
  or 32-bit — do not add version/bitness branching. Headless mode (`-Headless` /
  `LV_RTE_HEADLESS=1`) skips license activation for CI, so no license server needs
  to be reachable from the runner.
- **Container platform (Windows vs Linux) *is* branched**, unlike version/bitness:
  NI's two image families have different mount layouts, so `labview.platform`
  (inferred from the image tag) selects `C:\work`/`C:\out` + an explicit
  `-LabVIEWPath` for Windows, or `/work`/`/out` for Linux. See
  `container_paths()` in `src/fscicd/labview/container.py`.
- **Mass Compile has no machine-readable output.** `LabVIEWCLI` writes a
  plain-text log, so `parse_masscompile_log()` reads it. The real 2026 container
  format is one `CompileFile:` line per file — see the captured
  `tests/fixtures/masscompile_windows_2026.log`:

  ```
  CompileFile: error 74 at C:\work\Signal Generator.lvproj
  CompileFile: skipping C:\work\Signal Generator\Apply Window.vi
  MassCompile operation succeeded.
  ```

  Three traps, all of which produced a **false green** before being fixed:
  the operation reports `succeeded` even when individual files errored, so its
  verdict cannot be trusted alone; the exit code is `0` in that case too; and the
  log is ASCII/CRLF, so encoding must be sniffed by BOM/NUL rather than by trial
  decoding (ASCII decodes "successfully" as UTF-16 into mojibake and every marker
  silently disappears). A `skipping` line is *not* treated as a failure — LabVIEW
  does not say why it skipped, so an already-current VI and an unreadable one look
  identical — but compiled/skipped counts are always reported so "skipped
  everything" cannot masquerade as "compiled cleanly".
- **Unit tests cannot run in the stock NI image at all.** `RunUnitTests` fails
  there with `-350053` ("missing or bad files") because the UTF JUnit Report
  library is absent, and Caraya and VI Tester are VIPM packages rather than CLI
  operations — so one `-TestFramework` flag was never going to drive all three.
  Enabling this capability requires a worker image with those packages baked in
  via VIPM, which FSCICD does not build. `ContainerRunner.unit_tests()` raises
  with that explanation; `parse_junit_report()` is kept because the UTF JUnit
  library does emit JUnit XML once installed.
- **VI Analyzer cannot run without a `.viancfg`.** `RunVIAnalyzer` fails with
  `-350050` unless `-ConfigPath` names a VI Analyzer configuration, and one can
  only be authored in the LabVIEW IDE — FSCICD cannot synthesise it. The runner
  discovers the shallowest `.viancfg` in the checkout, or raises with that
  explanation. A `.viancfg` also carries statically mapped target paths from the
  machine that authored it, which do not exist under the container's `C:\work`
  mount, so a committed config needs its targeting rewritten at run time.
- **The VI Analyzer report is tab-separated plain text**, whatever extension
  `-ReportPath` is given — not HTML and not JSON. `-ReportPath` is required, a
  format argument is not, and `RunVIAnalyzer` exits **3** when analysis completed
  but tests failed, exactly like MassCompile. See the captured
  `tests/fixtures/vi_analyzer_report_windows_2026.txt`. VI Analyzer reports no
  severity of its own, so `parse_vianalyzer_report()` imposes one; only
  `Broken VI` is classified from observed output and everything else defaults to
  medium, which at the default `fail_on_severity: high` means unclassified
  findings are reported without failing the pipeline.
- **A `.viancfg`'s `<Path>"."</Path>` resolves relative to the config file's own
  directory**, not the mount root or the working directory. Values in that XML
  are quoted inside the element and backslashes are doubled
  (`<RelativePath>"project\\_VI Analyzer\\..."</RelativePath>`), so any rewrite
  must match that. Scope therefore follows wherever the config is committed,
  which is why a shared default config would need its targeting rewritten per
  run.
- **Per-operation `-Help` does not work** in this container: `LabVIEWCLI
  -OperationName <op> -Headless -Help` ignores `-Help` and attempts the
  operation, so required arguments are discovered from its `-350050` errors one
  at a time. Note `-Headless` is required even to reach that point, since
  operation handling needs a running LabVIEW.
- **Mock results are deterministic by file path** (seeded from the VI path): a VI
  whose name contains `broken` is reported broken, `missing` yields a missing
  dependency, VI Analyzer findings are stable per path, and a unit-test VI whose
  name contains `fail` (or `broken`) produces failing cases. Sample fixtures under
  `examples/sample-labview-project/` are named so the pipeline passes; the
  `examples/broken-project/` fixture is intentionally failing.
- **Capabilities live in `src/fscicd/capabilities/`** and are wired in
  `pipeline.py`. Adding one = new capability module + runner method (mock +
  container) + a report section in `templates/report.html.j2` + config in
  `config.py`. Unit tests are discovered via `test_globs` (default matches
  `*Test*.vi` and files under a `Tests/` folder).
- **Bitbucket credentials come from env vars only** (`BITBUCKET_USERNAME` +
  `BITBUCKET_APP_PASSWORD`, or `BITBUCKET_ACCESS_TOKEN`). With none set, status
  posting runs in dry-run mode, so the pipeline is fully runnable offline.
- **Reports** are written to `build/reports/` (git-ignored). `fscicd run` exits
  non-zero (2) when the pipeline status is FAILED — expected for the broken fixture.
