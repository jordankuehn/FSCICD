# FSCICD — Full-Stack CI/CD for LabVIEW

FSCICD runs real CI/CD quality gates for LabVIEW code: **Mass Compile**,
**VI Analyzer**, and **Unit Tests** (Caraya / VI Tester / NI UTF), executed inside
NI's official **headless LabVIEW containers**, with results rendered as a
shareable report and reported back to **Bitbucket** as commit build statuses.

CI runs **entirely on Bitbucket**: Bitbucket is the code of record *and* the CI
host, via **Bitbucket Pipelines**. There is no GitHub mirror and no GitHub
Actions workflow.

Because most LabVIEW work targets Windows — and Atlassian does not offer hosted
Windows runners — the real LabVIEW jobs run on a **self-hosted Bitbucket Windows
runner** driving the NI Windows container. Cloud (Linux) steps are used for the
parts that need no LabVIEW.

## Why containers (and no license server)

FSCICD assumes **LabVIEW 2026 64-bit everywhere**. NI's official images
(`nationalinstruments/labview:*`) support a **headless mode** in which
`LabVIEWCLI` operations (Mass Compile, VI Analyzer, etc.) run **without license
activation** for CI/CD — invoke with `-Headless` or set `LV_RTE_HEADLESS=1`. This
means no license server needs to be reachable from the runner.

## Architecture

```
Bitbucket repo (code of record)
        │
        ▼
Bitbucket Pipelines
        ├── cloud Linux step ── lint / unit tests / mock pipeline (no LabVIEW)
        │
        └── self-hosted Windows step  (runs-on: self.hosted, windows, labview)
                    │
                    ▼
            docker run nationalinstruments/labview:*-windows  (headless)
                    │
              Mass Compile ──▶ LabVIEWCLI log ──▶ FSCICD report (HTML + JSON)
                                                        │
                                       Bitbucket commit build status ◀── report URL
```

The LabVIEW execution backend is **pluggable**:

| Runner | Use |
|---|---|
| `mock` | Local dev / CI of FSCICD itself. Deterministic simulator, no LabVIEW needed. |
| `container` | Real runs on a Docker host with the NI headless image. |

This lets the orchestration, reporting and Bitbucket integration be developed and
tested with **no LabVIEW install**.

The `container` runner supports both NI image families. The platform is inferred
from the image tag, because the two images have different filesystem layouts:

| `labview.image` | Platform | Mounts | `-LabVIEWPath` |
|---|---|---|---|
| `...:2026q1-windows` | `windows` | `C:\work`, `C:\out` | LabVIEW.exe under Program Files |
| `...:2026q1-linux` | `linux` | `/work`, `/out` | resolved by LabVIEWCLI |

Set `labview.platform` explicitly only when the tag does not encode it.

## Bitbucket Pipelines setup

The cloud Linux step needs nothing. The Windows step needs a runner you host:

1. **Register the runner** — Bitbucket → Repository (or Workspace) settings →
   **Runners** → add a **Windows** runner. This repo's pipeline expects the
   labels `self.hosted`, `windows`, `labview`.
2. **Docker Desktop → Windows containers** — right-click the tray icon and
   choose *Switch to Windows containers*. Verify with
   `docker info --format '{{.OSType}}'` (expect `windows`).
3. **Pull the image** — `docker pull nationalinstruments/labview:2026q1-windows`
   (~10 GB). Smoke-test with
   `docker run --rm nationalinstruments/labview:2026q1-windows LabVIEWCLI -Help`.
4. **Install Python 3.10+** on the runner host and make sure it is on `PATH`.
5. *(Optional)* add `BITBUCKET_USERNAME` + `BITBUCKET_APP_PASSWORD` as secured
   repository variables to post commit build statuses. Without them, status
   posting is a dry run and the pipeline still passes.

Windows runners execute steps in **PowerShell on the host**, not in a container,
so they are not isolated from your desktop and share its CPU/RAM. Running
LabVIEW inside the NI container (as this pipeline does) keeps CI away from your
interactive LabVIEW IDE install. Two consequences worth knowing:

- **`DOCKER_HOST` must be overridden.** Pipelines injects
  `DOCKER_HOST=tcp://localhost:2375` for the Docker service it provides on *cloud*
  runners. A self-hosted Windows runner has no such service — Docker Desktop
  listens on `npipe:////./pipe/docker_engine` — so without the override every
  `docker` call fails with `connectex: No connection could be made`. The pipeline
  sets it per command.
- **Run the runner unelevated.** Files created by an elevated process are owned by
  `BUILTIN\Administrators`, which leaves checkouts and artifacts your own account
  cannot cleanly touch (`git status` reports *dubious ownership*). Docker access
  comes from the `docker-users` group, not from admin rights.

To add FSCICD to a LabVIEW application repository, copy
[`examples/bitbucket-pipelines.app-repo.yml`](examples/bitbucket-pipelines.app-repo.yml)
to its root as `bitbucket-pipelines.yml` and commit an `fscicd.yml` based on
[`examples/fscicd.windows.yml`](examples/fscicd.windows.yml).

## Worker image for a project with VIPM dependencies

The stock NI image runs LabVIEW but knows nothing about a project's VIPM
add-ons, so a real project's VIs load broken. Measured against a 1642-VI project
needing 148 packages, only 207 VIs (13%) were analyzable on the stock image, and
mounting a developer machine's `vi.lib`, `user.lib` and `instr.lib` raised that
only to 255 — copying files is not installing, which also does registry,
`Settings.ini` and palette registration.

[`docker/labview-worker.windows.Dockerfile`](docker/labview-worker.windows.Dockerfile)
installs them properly, with VIPM, at build time:

```powershell
# 1. Stage the project's VIPM configuration (git-ignored)
Copy-Item "path\to\Your Project.vipc" docker\vipm\

# 2. Build, with Docker in Windows-container mode
docker build -f docker/labview-worker.windows.Dockerfile -t fscicd-labview:2026q3-windows .
```

Then point `fscicd.yml` at the result:

```yaml
labview:
  image: fscicd-labview:2026q3-windows
  platform: windows
```

A `.vipc` that **bundles** its packages also works, and is required when a
project depends on in-house packages published on no VIPM repository: the
installer extracts the bundled payloads so they can be installed from file.

The base image, the VIPM-in-a-container technique, and the workarounds in
[`docker/vipm/install-vipc.ps1`](docker/vipm/install-vipc.ps1) come from
[LabVIEW-CI-with-Containers](https://github.com/elijah286/LabVIEW-CI-with-Containers),
used with the author's permission.

## Install (development)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Usage

```bash
# Run the pipeline against a checkout (mock runner by default in the example config)
fscicd run --config examples/fscicd.yml \
  --repo-path "examples/sample-labview-project" --commit "$(git rev-parse HEAD)"

# Real run in the NI Windows container (on a Windows host with Docker)
fscicd run --config examples/fscicd.windows.yml \
  --repo-path "examples/sample-labview-project" --commit "$(git rev-parse HEAD)"
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
| `bitbucket-pipelines.yml` | This repo's CI: cloud self-test + Windows LabVIEW step |
| `examples/bitbucket-pipelines.app-repo.yml` | Pipeline template for a LabVIEW app repo |
| `examples/` | Example configs + sample LabVIEW project fixtures |
| `tests/` | pytest suite |

## Development commands

```bash
.venv/bin/ruff check .        # lint
.venv/bin/ruff format --check .
.venv/bin/pytest              # tests
.venv/bin/yamllint bitbucket-pipelines.yml examples
```

## Status

| Capability | `mock` runner | `container` runner |
|---|---|---|
| Mass Compile | Implemented | **Working** — verified against a real container log |
| VI Analyzer | Implemented | Invocation correct; report parsing unproven |
| Unit Tests | Implemented | **Blocked** — needs a custom worker image |

Both are disabled in
[`examples/fscicd.windows.yml`](examples/fscicd.windows.yml), for different
reasons.

**VI Analyzer** needs a `.viancfg`, which selects the tests to run and can only be
authored in the LabVIEW IDE — `RunVIAnalyzer` refuses to start without one
(`-350050`). FSCICD discovers a committed configuration, but its report arguments
have not been exercised against a real run yet.

**Unit Tests** cannot run in the stock NI image: `RunUnitTests` fails with
`-350053` because the UTF JUnit Report library is absent, and Caraya and VI Tester
are VIPM packages rather than CLI operations. This needs a worker image with those
packages baked in via VIPM — the reason
[`docker/labview-worker.Dockerfile`](docker/labview-worker.Dockerfile) exists,
though it currently only extends the Linux image and installs nothing.

Roadmap after those: VIDiff, VI Browser, Antidoc, and an aggregated multi-commit
dashboard.
