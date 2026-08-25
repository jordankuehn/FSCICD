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
- **The image quarter must match the LabVIEW the VIs were saved in.** The projects
  are on **2026 Q3**, so the configs pin `nationalinstruments/labview:2026q3-*`.
  LabVIEW will not load VIs saved by a newer build, so running a `2026q1` image
  against a Q3 codebase reports breakage that has nothing to do with the code. The
  quarter is a deployment detail, not the version/bitness branching ruled out
  above.
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
- **LabVIEW operations can hang rather than fail**, so every container invocation
  is bounded by `labview.timeout_minutes` (default 120). Killing the docker client
  does not stop the container, so each run is given a `--name` and force-removed
  on timeout.
- **Mounting a developer machine's LabVIEW directories into the container supplies
  some of a project's VIPM dependencies, but not all.** Measured against FS
  iControl (1642 VIs, 148 packages): no mounts 207 passing;
  `vi.lib` + `user.lib` + `instr.lib` 255; additionally `resource` + `project` +
  `menus` also 255, so those three add nothing here. Both figures depend on the
  host directories actually being complete — an intermediate run scored 217 only
  because one of the project's own packages had been moved out of the host tree,
  which is worth remembering before reading anything into a drop.
  Eliminated as causes, all measured at the same 255: additionally mounting
  `resource`/`project`/`menus`; mounting
  `C:\Program Files\National Instruments\Shared`; the LabVIEW image quarter (a Q1
  and a Q3 run produced byte-identical reports); and sibling project sources,
  tested by mounting the whole parent directory **at its host path** inside the
  container so both relative and absolute references resolve. Every run reports
  `0 VIs were unloadable`, so LabVIEW loads each VI and finds it broken. Do not
  add further mount permutations: the file dimension is now exhausted, see the
  replication result below.
- **Copying the developer machine's whole installed tree into the image scores
  the same 255, so files are not what is missing.** This goes well past the
  mount experiments: `vi.lib`, `user.lib`, `instr.lib`, `resource`, `project`,
  `menus`, `examples`, `templates` and `AppLibs` from the host's LabVIEW 2026,
  plus the 64-bit `National Instruments\Shared` tree, plus the 168 NI-owned
  DLLs in `C:\Windows\System32` (`nisyscfg.dll`, `nicaiu.dll`, the VISA and IVI
  set) — 22 741 files added to `vi.lib` alone, 42 731 to `Shared`, every package
  the project needs verifiably present afterwards (`vi.lib\SEF Energy` 1814
  files, `GPower` 1204, `Delacor` 147). Result: **255 of 1642**, identical to
  the three-library mount, in 16 minutes. Re-run against a freshly re-copied
  source tree it is **251 of 1648** — the same 15%. So the two remaining
  suspects from the mount work, NI driver installs and system DLLs, are both
  eliminated, and whatever breaks these VIs is not a file that exists on the
  developer's machine. The copies are additive (`robocopy /XC /XN /XO`, which
  copies only files absent at the destination) so NI's own baseline in the image
  is never overwritten; the image and the host are both LabVIEW `26.3f0`.
- **Do not import the host's NI registry hives into the container — it breaks
  LabVIEW.** Importing `HKLM\SOFTWARE\National Instruments`, its `WOW6432Node`
  twin and `HKLM\SOFTWARE\JKI` leaves LabVIEW launching but never opening VI
  Server, so `LabVIEWCLI` fails with `-350000` ("failed to establish a
  connection with LabVIEW ... ensure LabVIEW is running with VI server enabled
  on the correct port"). Without the import, VI Server is listening on 3363
  **12 seconds** after launch. That kills the "activation/registry state for the
  licence-gated packages" theory as a *practical* route even before asking
  whether it would have helped.
- **When something has been added to `vi.lib`, launch LabVIEW yourself and wait
  for port 3363 rather than letting `LabVIEWCLI` launch it.** The CLI's own
  connect window is short and its failure (`-350000`) looks identical to a
  broken LabVIEW, which sends you diagnosing the wrong thing. Start
  `LabVIEW.exe`, poll `netstat` for a listener on 3363, then call `LabVIEWCLI
  -PortNumber 3363`. See `Test-VipmFileHandler`'s sibling logic in
  `docker/vipm/` for the pattern.
- **Do not try to identify missing dependencies by scanning VI binaries for
  strings.** It reads as evidence and is almost entirely noise. Measured against
  this project it "found" `Unload.lvclass` referenced by 1381 of 1540 VIs, which
  matched the 1387 failures almost exactly and was pure coincidence: the real
  string is `Load & Unload.lvclass` (NI's icon editor) and the `&` fell outside
  the character class. Likewise `Casting Utility For Actors.vi` is really a
  `.vim`, `Message Enqueuer.ctl` is class private data, and the GUID-named VIs
  are packed-library internals — LabVIEW's own `LVStatus.txt` shows it loading
  `GSW.lvlibp\1abvi3w\...\134e4d3a-....vi`. Name-only matching can only ever
  prove absence, and it cannot even do that for anything inside a `.lvlibp`.
- **What is actually still unexplained**: LabVIEW loads all 1642 VIs (`0 VIs were
  unloadable`) and calls ~85% of them broken, uniformly across every module
  (`_Code\FS iControl` 347, `Well` 199, `Source` 167, `Valve` 138, and so on
  down), with a single reason, `Broken VI`. It is not the file set, not the
  image quarter, not sibling sources, and not the freshness of the copy. The
  untested question is no longer *what is missing from the container* but
  **whether these VIs are broken on the developer's machine too** — nobody has
  ever confirmed the project loads clean in LabVIEW 2026. Two things hint that
  it might not: every `.lvproj` still carries `LVVersion="23008000"` (LabVIEW
  2023) though 391 of 407 classes and libraries are saved at `26008000`, and NI
  System Configuration (`nisyscfg.lvlib`, which the project's VIs call) is
  installed for the host's LabVIEW **2023** and not for its 2026. The cheap next
  experiment is to point VI Analyzer at a package's own VIs — say
  `vi.lib\SEF Energy` — instead of the project: if the dependencies are broken
  in the container too, the cause is environmental and downstream breakage is
  just propagation.
- **Keep the analysis copy honest.** `C:\temp\fsic` had drifted from the source:
  36 files missing (including five message classes the project's libraries
  declare as members), 24 files present that the source does not have, and 2088
  differing in size because Mass Compile had rewritten them in place. It changed
  nothing here — a re-copied tree scored the same 15% — but every number before
  this was measured against it. Re-copy from source before a measurement that
  matters, and remember the `.viancfg` lives only in the copy.
- **VIPM cannot install packages in NI's 2026 Windows container at all, and the
  cause is a crash in JKI's own binaries.** The CLI never opens a socket: it
  reaches VIPM by launching `VIPM File Handler.exe -- /command:<op>
  /progress_file:<tmp> /return_file:<tmp>` and polling for the return file. That
  LabVIEW-built helper dies with `0xC0000005` two to three seconds in, before
  writing either file, so the CLI polls a file that never appears until the
  operation reports `Operation 'wait for VIPM startup' timed out`.
  `%TEMP%\LVStatus.txt` records `Recursive load during LEIF load! ... VIPM -
  Check is Windows Task Runnning by Name (Scalar).vi is loading ...\System`.
  `VIPM Update Registry.exe` and `LabVIEW Tools Network.exe` fail the same way;
  `JKIUpdate.exe`, the only non-LabVIEW helper, exits 0; LabVIEWCLI is healthy in
  the same container. `install-vipc.ps1` preflights that hop and fails in
  seconds — do not "fix" it by raising timeouts or restarting the engine.
  Eliminated, all measured: the engine crashing (it stays alive and
  `Responding`, and holds no port by design, so `Responding=True` proves
  nothing); a slow first launch (watched 8 minutes, engine idle at 3s CPU);
  the zero-byte `Settings.ini` (**written by the failing CLI when the file is
  absent** — a seeded file survives an engine launch untouched, so the re-seed
  logic that was added for it has been removed); missing .NET (Framework 4.8 is
  complete and every assembly the helper loads works from PowerShell);
  licensing; `docker build` vs `docker run` (identical failure, so the old
  window-station theory was wrong); and local-file vs by-name installs (both
  block on the same helper). `LV_RTE_HEADLESS=1` only aggravates it: unset, the
  helper exits cleanly but still answers nothing. Note `vipm version` is **not**
  a usable readiness check — it prints `2026.3.0 Free Edition` instantly with no
  engine running and no `Settings.ini`. JKI have the same class of bug open on
  Linux ([vipm-desktop-issues#126](https://github.com/vipm-io/vipm-desktop-issues/issues/126)),
  where 2025 images work and 2026 ones do not; there is no Windows fallback,
  because NI publish no Windows image before 2026 and the working 2025 images are
  Linux-only.
- **`Settings.ini` must follow JKI's container format**, not an invented one:
  `Versions 0` carries the **year** (`26.0 (64-bit)`) while
  `Active Target.Version` carries the **quarter** (`26.3 (64-bit)`). With the
  quarter in both, the CLI cannot detect a target at all
  ("Failed to detect LabVIEW version automatically"); with the year in place it
  reports "Auto-detected LabVIEW 2026 (64-bit)". The file also needs
  `[Repository] LVTN TOS Agreed MD5` to pre-accept the LabVIEW Tools Network
  terms, and the `[General]` update-check and download-warning suppressions, so
  nothing waits on a dialog no one can see. See `Set-VipmSettings` in
  `docker/vipm/install-vipc.ps1`.
- **Mass Compile hangs on a project whose dependencies are missing; VI Analyzer
  does not.** Against a 1642-VI project needing 148 absent VIPM packages,
  MassCompile logged only "Connection established with LabVIEW" and never reached
  `#### Starting Mass Compile` — once for 17 hours from a cloud-synced folder with
  library mounts, and again for 41 minutes from local disk with none, so neither
  the sync nor the mounts caused it. LabVIEW appears to search the disk for each
  unresolvable subVI. VI Analyzer completed the same tree in 21–25 minutes and
  reported per-VI. **Do not use Mass Compile to diagnose missing dependencies**;
  it will only burn the timeout. Note also that MassCompile writes recompiled VIs
  back to the checkout while VI Analyzer only reads, so it is additionally
  sensitive to a slow working directory.
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
