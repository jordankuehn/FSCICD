# AGENTS.md

FSCICD is a **CI/CD system for LabVIEW code**. It runs Mass Compile and VI
Analyzer inside NI's official **headless LabVIEW containers**, renders an
HTML/JSON report, and posts a **Bitbucket** commit build status.

**CI runs on Bitbucket Pipelines. The Bitbucket → GitHub mirror is retired** —
do not reintroduce it, and do not treat `.github/workflows/` as the LabVIEW CI
engine (it is only a smoke test of the orchestrator on this repo's GitHub
remote). Real LabVIEW jobs run on a **self-hosted Bitbucket Windows runner**
(labels `self.hosted`, `windows`, `labview`) because Atlassian hosts no Windows
runners and the projects target Windows. `src/fscicd/mirror.py` and the
`fscicd mirror` CLI are legacy leftovers.

Key packages:
- `src/fscicd/` — Python package. Entry point CLI is `fscicd` (see `cli.py`).
- `src/fscicd/labview/` — pluggable LabVIEW backends: `mock` (deterministic
  simulator, no LabVIEW needed) and `container` (real, `docker run` the NI image).
- `bitbucket-pipelines.yml` — this repo's CI (cloud self-test + Windows LabVIEW
  step); `examples/bitbucket-pipelines.app-repo.yml` is the template LabVIEW
  application repos copy.
- `docker/labview-worker.Dockerfile` — Linux worker on the NI headless image.

## Cursor Cloud specific instructions

- **Python dev env lives in `.venv`.** After the update script runs, use
  `.venv/bin/<tool>` (e.g. `.venv/bin/pytest`, `.venv/bin/ruff`) or activate the
  venv. The package is installed editable, so `src/fscicd` edits take effect
  without reinstalling.
- **Standard commands** (all from repo root):
  - Lint: `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  - Tests: `.venv/bin/pytest`
  - YAML lint (CI configs): `.venv/bin/yamllint .github/workflows bitbucket-pipelines.yml examples`
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
  plain-text log (sometimes UTF-16), so `parse_masscompile_log()` reads the
  `### Bad VI:` / `Search failed to find ... Caller:` markers. Exit code `3` means
  "finished with bad VIs" and must be parsed, not treated as a runner error. VI
  Analyzer and Unit Tests still parse report shapes the real operations do not
  emit, so they are disabled in `examples/fscicd.windows.yml` until ported.
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
