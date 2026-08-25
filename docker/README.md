# Building the Windows worker image

The stock NI image runs LabVIEW but knows nothing about a project's VIPM
add-ons, so a real project's VIs load broken. Measured against a 1642-VI project
needing 148 packages, only 207 VIs were analyzable on the stock image, and
mounting a developer machine's `vi.lib`, `user.lib` and `instr.lib` raised that
only to 255 — copying files is not installing, which also does registry,
`Settings.ini` and palette registration.

This image installs the packages properly, with VIPM.

## Why it is two steps rather than a `docker build`

The VIPM CLI does not install anything itself: it delegates to an engine that is
a LabVIEW-runtime GUI application. Measured in the NI Windows container:

| | Engine after 60s |
|---|---|
| `docker run` | alive, `Responding = True` |
| `docker build` | never completes startup; every call fails with `Operation 'wait for VIPM startup' timed out` |

Windows build steps run their children on a non-interactive window station,
which the engine evidently cannot use. So the packages are installed by running
a container and committing the result, which is a normal Docker technique for
exactly this class of problem.

## 1. Stage the tooling

Copy the project's VIPM configuration into `docker/vipm/` — git-ignored, because
these are large and project-specific:

```powershell
Copy-Item "path\to\Your Project.vipc" docker\vipm\
```

Use a configuration that **bundles** its packages if the project depends on
in-house packages published on no VIPM repository. The installer extracts the
bundled `.vip` payloads and installs from them, which needs no package index and
is the only route for a package no mirror carries.

Then build the staging image, from the repository root with Docker in
Windows-container mode:

```powershell
docker build -f docker/labview-worker.windows.Dockerfile -t fscicd-labview:staging .
```

## 2. Install the packages and commit

```powershell
docker run --name fscicd-vipm-install fscicd-labview:staging powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "New-Item -ItemType Directory -Force C:\vipmwork | Out-Null; Copy-Item C:\vipm\* C:\vipmwork\ -Recurse -Force; $env:VIPC_DIR='C:\vipmwork'; & C:\vipmwork\install-vipc.ps1"
```

The installer works in a container-local directory because extracting a bundled
configuration writes hundreds of megabytes, which should not land in a
bind-mounted source tree.

This takes a long time — every package installs against a live headless LabVIEW.
The log names each package it installs and each one that fails.

When it finishes, commit the container to the image FSCICD will use:

```powershell
docker commit fscicd-vipm-install fscicd-labview:2026q3-windows
docker rm fscicd-vipm-install
```

## 3. Point FSCICD at it

```yaml
labview:
  runner: container
  image: fscicd-labview:2026q3-windows
  platform: windows
```

`platform` is inferred from the tag, so a name ending `-windows` needs no
explicit setting.

## Verifying it worked

Re-run an analysis and compare against the stock image. On the reference project
that was 207 analyzable VIs before, and 255 with the developer machine's
libraries mounted:

```powershell
docker run --rm -v "C:\path\to\project:C:\work" -v "C:\temp\out:C:\out" -e LV_RTE_HEADLESS=1 fscicd-labview:2026q3-windows LabVIEWCLI -OperationName RunVIAnalyzer -ConfigPath "C:\work\Your Tests.viancfg" -ReportPath "C:\out\report.txt" -Headless
```

No library mounts: the packages are in the image.

## Attribution

The base image, the VIPM-in-a-container technique, and the workarounds in
`vipm/install-vipc.ps1` come from Elijah Kerry's
[LabVIEW-CI-with-Containers](https://github.com/elijah286/LabVIEW-CI-with-Containers),
used with the author's permission.
