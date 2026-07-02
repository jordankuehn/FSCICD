# FSCICD — Full-Stack CI/CD for LabVIEW

FSCICD runs real CI/CD quality gates for LabVIEW code: **Mass Compile** and
**VI Analyzer** (with more capabilities to follow), executed inside NI's official
**headless LabVIEW containers**, with results rendered as a shareable report and
reported back to **Bitbucket** as commit build statuses.

It is built around **Option B**: your code of record lives in **Bitbucket**, and
repositories are mirrored into **GitHub** so the containerized LabVIEW CI runs on
GitHub Actions.

## Why containers (and no license server for 2026)

NI's official images (`nationalinstruments/labview:*`) support a **headless mode**
starting **LabVIEW 2026 Q1**. In headless mode, `LabVIEWCLI` operations
(Mass Compile, VI Analyzer, etc.) run **without license activation** for CI/CD —
invoke with `-Headless` or set `LV_RTE_HEADLESS=1`. FSCICD targets 2026 64-bit
for this reason. (LabVIEW 2023 has no headless mode and would require NILM
activation against your volume license server inside a Windows container.)

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

MVP: **Mass Compile + VI Analyzer**. Roadmap: VIDiff, VI Browser, Unit Tests,
Antidoc, aggregated dashboard (mirroring the capabilities of the reference
project this is based on).
