# Building the Windows worker image

The stock NI image runs LabVIEW but knows nothing about a project's VIPM
add-ons, so a real project's VIs load broken. Measured against a 1642-VI project
needing 148 packages, only 207 VIs were analyzable on the stock image, and
mounting a developer machine's `vi.lib`, `user.lib` and `instr.lib` raised that
only to 255 — copying files is not installing, which also does registry,
`Settings.ini` and palette registration.

This image is intended to install the packages properly, with VIPM.

## Status: blocked by a crash in VIPM's own helper

**VIPM cannot install packages in NI's 2026 Windows container at all today.**
`install-vipc.ps1` detects this up front and fails in seconds rather than
spending the timeout to reach the same conclusion.

The VIPM CLI never opens a socket. It reaches VIPM by launching a second
LabVIEW-built executable with a command name and a pair of temp files, and
polling for the return file:

```
VIPM File Handler.exe -- /command:vipm_status
  /progress_file:<tmp> /return_file:<tmp>
```

In this container that helper dies with `0xC0000005` (access violation) two to
three seconds in, before creating either file. The CLI then polls for a file
that will never appear until the operation gives up with
`Operation 'wait for VIPM startup' timed out`. LabVIEW records the fault in
`%TEMP%\LVStatus.txt`:

```
Recursive load during LEIF load! ...\VIPM File Handler.exe\JKI Reuse Pool\Windows\
VIPM - Check is Windows Task Runnning by Name (Scalar).vi is loading ...\System
```

What that rules out, all measured in the same image:

| Suspect | Finding |
|---|---|
| The engine is crashing | No. `VI Package Manager.exe` (which the CLI calls "VIPM Desktop") stays alive and `Responding`, and holds no listening port because it is not meant to |
| A slow first-launch handshake | No. Watched for 8 minutes: engine idle at 3s CPU, package index untouched, install still failing |
| Empty `Settings.ini` | Symptom, not cause. The failing CLI creates it when absent; a seeded file survives an engine launch untouched |
| Missing .NET | No. .NET Framework 4.8 is complete and `System`, `System.Drawing`, `System.Windows.Forms` and `System.IO.Compression.FileSystem` all load fine |
| Licensing | No. `Valid Activation Code: true`, and JKI document activation as optional for Free/Community |
| `docker build` vs `docker run` | Irrelevant. Identical failure both ways, so the old window-station theory was wrong |
| `LV_RTE_HEADLESS=1` | Aggravating only. It turns the fault into a hard crash; unset, the helper exits cleanly but still writes no return file |
| Broken only for local files | No. By-name installs block on the same helper |

It is specific to LabVIEW-built VIPM components: `VIPM Update Registry.exe` and
`LabVIEW Tools Network.exe` fail identically, while `JKIUpdate.exe` — the one
helper that is not a LabVIEW app — exits 0. LabVIEWCLI itself is healthy in the
same container, which is why analysis works and only installation does not.

Upstream, JKI have an open report of the same class of failure on Linux
([vipm-desktop-issues#126](https://github.com/vipm-io/vipm-desktop-issues/issues/126)),
where `vipm-desktop` goes defunct on 2026 images and the reporter notes that
2025 images install correctly. There is no Windows equivalent to fall back to:
NI publish no Windows image before 2026 (`2026q1`, `2026q1patch1`,
`2026q1patch2`, `2026q3`, `latest`), and the working 2025 images are Linux-only.

Until this is fixed upstream, use the stock image and accept the reduced
analysis coverage, or supply the dependencies by another route.

## Why the install is a run-and-commit rather than a `docker build`

Because the installer needs a live LabVIEW and a live VIPM engine, which is
awkward inside a single `RUN`, the packages are installed by running a container
and committing the result — a normal Docker technique for this class of problem.
The steps below are kept for when the upstream crash is fixed.

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
