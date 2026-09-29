# Building the Windows worker image

The stock NI image runs LabVIEW but knows nothing about a project's VIPM
add-ons, so a real project's VIs load broken. Measured against a 1642-VI project
needing 148 packages, only 207 VIs were analyzable on the stock image, and
mounting a developer machine's `vi.lib`, `user.lib` and `instr.lib` raised that
only to 255 — copying files is not installing, which also does registry,
`Settings.ini` and palette registration.

This image is intended to install the packages properly, with VIPM.

## Status (2026-09-28)

VIPM package installs in NI's 2026 Windows container **work** when the LCWC
recipe is followed: container memory ≥2.5 GB (`docker run -m 8GB`),
`LV_RTE_HEADLESS` cleared for the install process tree (image ENV can stay set
for runtime LabVIEWCLI), JKI `Settings.ini` with year in `Versions 0` and
quarter in `Active Target.Version`, and `vipm refresh --force` before any
library operation. Details and the false leads eliminated along the way are in
`AGENTS.md`.

**Working measurement image today:** `fscicd-labview:2026q3-windows-vipm`
(hand-assembled after a successful install). Do **not** use the committed tag
`fscicd-labview:2026q3-windows` for analysis — every `LabVIEWCLI` call on that
image fails with `-350000` even though port 3363 listens. Re-bake and only
retag `2026q3-windows` after a connect + VIA probe passes. Also avoid
`2026q3-windows-replica` (host NI/JKI registry hives baked in).

Project VIA after overlaying today's fixed host `vi.lib\SEF Energy` packages:
**189 / 1510**. SEF Energy itself: **783 / 1074**, with
`fs-tx-actuator` / `fs-vx-actuator` / `fs-systemlink` clean and
`fs-choke-actuator` / `fs-daq-logger` / `fs-net-com` still the wall. See
`HANDOFF.md` and the 2026-09-28 remeasure bullet in `AGENTS.md`.

## Why the install is a run-and-commit rather than a `docker build`

The installer needs a live LabVIEW and a live VIPM engine, which is awkward
inside a single `RUN`, so packages are installed by running a container and
committing the result — a normal Docker technique for this class of problem.

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
docker run --name fscicd-vipm-install fscicd-labview:staging powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\vipm\install-in-container.ps1
```

Note the `-File`. An equivalent inline `-Command` needs nested quoting that the
*host* shell expands first — a `$env:VIPC_DIR='...'` written inline is
substituted before Docker sees it, leaving the variable unset in the container.
The wrapper also copies the tooling to a container-local directory, because
extracting a bundled configuration writes hundreds of megabytes and that should
not land in a bind-mounted source tree.

This takes a long time — every package installs against a live headless LabVIEW.
The log names each package it installs and each one that fails.

When it finishes, commit the container to the image FSCICD will use:

```powershell
docker commit fscicd-vipm-install fscicd-labview:2026q3-windows
docker rm fscicd-vipm-install
```

`install-in-container.ps1` runs `seed-eval-licences.ps1` after the VIPM install.
That copies each vendor's **as-shipped** `.lf` from `vi.lib` into
`ProgramData\National Instruments\Partners\<Vendor>\Licenses\`, which puts
TPLAT add-ons into their 30-day evaluation. Without this step, licensed
libraries analyse as broken even when the files are present. Do **not** copy a
developer machine's activated `Partners` tree instead — those files are bound
to the host's TPLAT computer number and fail to open in a container.

To run the seed step alone on an image that already has packages in `vi.lib`:

```powershell
docker run --rm fscicd-labview:2026q3-windows powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\fscicd\seed-eval-licences.ps1
```

## Mass Compile diagnostics

VI Analyzer only says "This VI is broken". To name the actual missing file or bad
subVI, run Mass Compile on **one library inside vi.lib** — not the whole project,
which hangs when dependencies are missing (see AGENTS.md).

Mass Compile **rewrites VIs in place**. Aim it only at the container's own
`vi.lib` copy or a throwaway project copy, never at a bind-mounted developer
tree.

One library:

```powershell
docker run --rm -v "C:\temp\out:C:\out" -e LV_RTE_HEADLESS=1 `
  fscicd-labview:2026q3-windows powershell -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File C:\fscicd\masscompile-dir.ps1 `
  -Directory "C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-net-com"
```

Several libraries in one LabVIEW session (`COMPILE_DIRS` or `-Directories`):

```powershell
docker run --rm -v "C:\temp\out:C:\out" -e LV_RTE_HEADLESS=1 `
  -e COMPILE_DIRS="C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-net-com;C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-choke-actuator" `
  fscicd-labview:2026q3-windows powershell -NoLogo -NoProfile -ExecutionPolicy Bypass `
  -File C:\fscicd\masscompile-dir.ps1
```

Logs land under `C:\out\` (mount `C:\temp\out` on the host). The script seeds TPLAT
evaluation licences first unless `SKIP_LICENCE_SEED=1`.

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
