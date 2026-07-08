# FSCICD — Full-Stack CI/CD for LabVIEW

FSCICD runs real CI/CD quality gates for LabVIEW code: **Mass Compile**,
**VI Analyzer**, and **Unit Tests** (Caraya / VI Tester / NI UTF), executed inside
NI's official **headless LabVIEW containers**, with results rendered as a
shareable report and reported back to **Bitbucket** as commit build statuses.

It is built around **Option B**: your code of record lives in **Bitbucket**, and
repositories are mirrored into **GitHub** so the containerized LabVIEW CI runs on
GitHub Actions.

## Why containers (and no license server)

FSCICD assumes **LabVIEW 2026 64-bit everywhere**. NI's official images
(`nationalinstruments/labview:*`) support a **headless mode** in which
`LabVIEWCLI` operations (Mass Compile, VI Analyzer, etc.) run **without license
activation** for CI/CD — invoke with `-Headless` or set `LV_RTE_HEADLESS=1`. This
means no license server needs to be reachable from the runner.

## Architecture

```
Bitbucket repo ──(mirror: git push --mirror)──▶ GitHub repo
                                                    │
                                          GitHub Actions (.github/workflows)
                                                    │
                             docker run nationalinstruments/labview (headless)
                                       │                         │
                                 Mass Compile               VI Analyzer
                                       └──────────┬──────────────┘
                                                  ▼
                                     FSCICD report (HTML + JSON)
                                                  │
                                    Bitbucket commit build status  ◀── report URL
```

The LabVIEW execution backend is **pluggable**:

| Runner | Use |
|---|---|
| `mock` | Local dev / CI of FSCICD itself. Deterministic simulator, no LabVIEW needed. |
| `container` | Real runs on a Docker host with the NI headless image. |

This lets the orchestration, reporting and Bitbucket integration be developed and
tested with **no LabVIEW install**.

## Install (development)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Usage

```bash
# Run the pipeline against a checkout (mock runner by default in the example config)
fscicd run --config examples/fscicd.yml --repo-path "examples/sample-labview-project" --commit "$(git rev-parse HEAD)"

# Preview the Bitbucket -> GitHub mirror commands
fscicd mirror origin https://github.com/<owner>/<repo>.git
```

`fscicd run` writes `report.html` + `report.json` under `report.output_dir` and
posts a Bitbucket build status (dry-run unless credentials are set).

### Bitbucket credentials (environment only)

```bash
export BITBUCKET_USERNAME=...        # + app password
export BITBUCKET_APP_PASSWORD=...
# or
export BITBUCKET_ACCESS_TOKEN=...    # repository/workspace access token
```

## Configuration (`fscicd.yml`)

See [`examples/fscicd.yml`](examples/fscicd.yml). A single file controls the
LabVIEW backend, enabled capabilities, and reporting.

## Repository layout

| Path | Purpose |
|---|---|
| `src/fscicd/` | Python package (config, runners, capabilities, report, Bitbucket, CLI) |
| `src/fscicd/labview/` | LabVIEW backends: `mock` and `container` |
| `docker/labview-worker.Dockerfile` | Linux worker built on the NI headless image |
| `.github/workflows/labview-ci.yml` | GitHub Actions LabVIEW CI (runs on the mirror) |
| `bitbucket-pipelines.yml` | Bitbucket → GitHub mirror step |
| `examples/` | Example config + sample LabVIEW project fixtures |
| `tests/` | pytest suite |

## Development commands

```bash
.venv/bin/ruff check .        # lint
.venv/bin/ruff format --check .
.venv/bin/pytest              # tests
.venv/bin/yamllint .github/workflows bitbucket-pipelines.yml
```

## Status

Implemented: **Mass Compile**, **VI Analyzer**, **Unit Tests**. Roadmap: VIDiff,
VI Browser, Antidoc, aggregated multi-commit dashboard (mirroring the reference
project this is based on).
