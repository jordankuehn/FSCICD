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
- **The dependencies are themselves partly broken in the container.** Analysing
  `vi.lib\SEF Energy` instead of the project — drop a copy of the `.viancfg`
  into the directory of interest, since its target is `<Path>"."</Path>`,
  resolved relative to the config's own folder — gives **697 of 946 passing
  (74%)** against the project's 15%. So the container is not globally broken;
  but 249 VIs inside the in-house package are, and the project sits on top of
  them, which is enough to explain the propagation. The failures cluster in
  exactly the IO-facing sub-libraries: `fs-daq-logger` 51, `fs-net-com` 63, the
  three actuator drivers 74, plus `Select FS System MAX.vi`.
- **`C:\Program Files\NI\LVAddons` is the missing layer, and it is a separate
  root that "replicate the LabVIEW tree" easily misses.** Since LabVIEW 2022 Q3
  drivers and toolkits install to this version-independent location instead of
  the version-specific LabVIEW folder, and LabVIEW virtually merges every
  `vi.lib` beneath it with `LabVIEW 2026\vi.lib`
  ([NI docs](https://www.ni.com/docs/en-US/bundle/labview/page/version-independent-add-ons.html)).
  The developer machine has **55** add-ons there, 1.46 GB and 33 085 files,
  including `nisyscfg`, `nidaqmx`, `nivisa`, `nixnet`, `crio` and `rseries`; the
  stock image has **4** (`dfc`, `utf32`, `utf64`, `viawin`). This corrects an
  earlier conclusion recorded here: LabVIEW 2026 on the developer's machine is
  **not** a less complete install than its 2023, and those package VIs are not
  broken there. `vi.lib\nisyscfg` and friends look absent for 2026 only because
  the content moved to LVAddons. Any tree replication must include this root.
- **But replicating LVAddons does not work in this container either — LabVIEW
  wedges.** Two distinct failures, in order. First, the `lvai` add-on (the IDE's
  AI assistant) floods `LVStatus.txt` with `Recursive load during LEIF load!`
  from `LV AI Core.lvlibp` and LabVIEW stops answering 3363, so `LabVIEWCLI`
  reports `-350000`. Excluding `lvai` clears those faults and LabVIEW starts
  clean — and then simply never analyses: **three hours** on one
  `RunVIAnalyzer`, LabVIEW flat at 140 MB and accumulating 2.8 CPU-seconds per
  45 wall seconds (~6% of one core), the CLI idle at 2 CPU-seconds, no report.
  That is not first-load compilation being slow, it is wedged. Note a listening
  port on 3363 is *not* readiness here, so retry the CLI rather than trusting it.
- **Copying only the add-ons the project needs does not help either: 252.** With
  `nisyscfg`, `nidaqmx`, `nivisa` and `nixnet` (plus their 32/64 variants) copied
  and nothing else — 12 add-ons present, LabVIEW starting clean and VI Server up
  in 12 seconds — the analysis completes in 11m43s at **252 of 1648**, against
  251 with no add-ons at all. One VI. So the ceiling has now been measured five
  ways (stock 207; three-library mount 255; whole-tree replication 255; fresh
  source 251; driver add-ons 252) and no arrangement of the developer machine's
  files moves it.
- **Packed libraries (`.lvlibp`) are broken here, but they are not why the
  project's VIs are broken.** Every `Recursive load during LEIF load!` names one:
  `JKI SDP.lvlibp` (JKI Design Palette), `GSW.lvlibp`, `LV AI Core.lvlibp`, and
  VIPM's own LabVIEW-built `VIPM File Handler.exe`, which dies with `0xC0000005`
  after logging exactly that. That is worth reporting to JKI and NI, since one
  bug would cover the VIPM install failure and the `lvai` wedge. It does **not**
  explain the broken VIs, though: the project contains **zero** `.lvlibp`, and so
  does `vi.lib\SEF Energy`, whose own VIs are 26% broken. Do not chase it as the
  cause of the 255.
- **So the broken VIs are environmental — and one of the missing files turned
  out to be a licence file.** The same sources that the owner reports loading
  cleanly in his IDE produce broken VIs in the container, and no permutation of
  the *LabVIEW tree* changed the number, including the per-user configuration
  (see below). What none of those permutations covered was
  `ProgramData\National Instruments\Partners`, and seeding that does move the
  number for the licensed libraries — see the TPLAT entries below before
  concluding anything from the 207/251/252/255 series.
- **Third-party toolkit licences live in
  `C:\ProgramData\National Instruments\Partners\<Vendor>\Licenses\<Product>_License.lf`,
  and the container needs one there or every VI in the library is broken.** This
  is NI's Third Party Licensing & Activation Toolkit (TPLAT). The licensed
  library states the arrangement itself: `WF_WireQueue-MQTT.lvlib` carries
  `NI.Lib.Lic.AO.LFName = WireQueue-MQTT_License.lf` and
  `NI.Lib.Lic.AO.ActivationURL = https://softwarekey.ni.com/solo/unlock`, so
  LabVIEW validates that file when it loads the library and — this being TPLAT
  *development* licensing, checked at edit time — marks every member VI broken
  when it does not validate. NI describe that as designed behaviour, not a
  malfunction: "Broken VIs when licensing state is invalid or expired" is on
  their own feature checklist for the toolkit. There are **two** copies of each
  `.lf`, same size and different hash: the as-shipped one beside the `.lvlib` in
  `vi.lib\addons\...`, and the activated one under `Partners`.
- **Seed the AS-SHIPPED `.lf` into `Partners`, not the activated one, and the
  add-on lands in its 30-day evaluation and works.** This is the fix, measured
  on `vi.lib\addons\WireFlow\_WireQueue`: **199 of 199 broken** with no licence
  file or with the host-activated one, **214 of 216 passing** with the vendor's
  own shipped file copied to
  `ProgramData\National Instruments\Partners\WireFlow\Licenses\`. It is what a
  real VIPM install puts there, and NI's tutorials state that a registered
  add-on "will start off in evaluation mode" with the run arrow unbroken. See
  `seed-eval-licences.ps1`, which walks every `.lf` under `vi.lib` and places it
  under its vendor. The activated copy is worse than useless — it is bound to
  the activating machine's TPLAT computer number, so it fails to open AND no
  evaluation begins.
- **`DPrintfLogging=True` in `LabVIEW.ini` is how to see any of this.** LabVIEW
  then logs its licensing decisions to
  `%TEMP%\LabVIEW_64_<ver>_headless_<user>_cur.txt`, tagged `LV2P`, and the
  verdict is explicit rather than inferred from broken VIs. Failing:

  ```
  LV2P - License path: ...\Partners\WireFlow\Licenses\WireQueue-MQTT_License.lf
  LV2P - Computer Number found to be : 101700461
  LV2P - Opening license file
  LV2P - Error opening license file
  LV2P - pp_eztrial1() returned with status : 0
  Bad License! The unlicensed library is: WF_WireQueue-MQTT.lvlib:Messaging.lvclass
  ```

  Working: `Successful in opening license file`, `pp_eztrial1() ... status : 2`,
  and zero `Bad License` lines. Two traps in that log. The
  `SoftwareKey Protection PLUS DLL (KEYLIB32.DLL) is invalid` signature
  complaints are **noise** — `KEYLIB64.dll` and `SKCA64.dll` carry no signature
  at all on the developer's machine either, and licensing works there — so do
  not chase them. And LabVIEW registers the add-on itself
  (`Writing the attributes of this add-on to the registry ... without any
  error`, under
  `HKLM\SOFTWARE\National Instruments\LabVIEW\26.0\PartnerAddons\<Vendor>\`), so
  `RegisterAddon.exe` is not needed; it exits 3 silently in this container
  anyway, being another LabVIEW-built helper of the kind that dies here.
- **The identifier TPLAT binds to is its own 9-digit computer number, not the NI
  Computer ID.** This corrects an earlier conclusion recorded here. The log
  reports `Computer Number found to be : 101700461`, which is what NI's offline
  activation page calls a User Code; `generateComputerId.exe` reports
  `6RZC-VFFQ-5C7V-TFC5`, which belongs to NI License Manager and is a different
  system. So "buy an activation for the container's Computer ID" was aimed at
  the wrong number — and is moot, because the evaluation route needs no
  activation. What remains true and useful: the value is stable across fresh
  containers from NI's published images, and `Licensing.log` records
  `Unknown host id [ffffffff]` from every NILM consumer in the container.
- **NI support unactivated LabVIEW in containers, and explicitly do not extend
  that to third-party add-ons.** Headless mode is the supported ephemeral story
  for LabVIEW itself: `-Headless` on every `LabVIEWCLI` call for 2026 Q1 and
  later (replacing `EnableCICDFeaturesForLabVIEW=TRUE` in 2025 Q3 and earlier),
  documented in
  [ni/labview-for-containers](https://github.com/ni/labview-for-containers/blob/main/docs/headless-labview.md)
  as running "without requiring activation", for non-development use only. On
  the licensing side the LabVIEW EULA has covered CI/CD use since August 2021,
  and VLA holders add free part number `786474-35` so a build machine does not
  consume a development seat. For add-ons NI say the opposite: "NI does not
  provide activation keys for third-party add-ons ... it is the responsibility
  of the third-party add-on developer", and there is no NI-supported switch that
  disables a TPLAT check. The 30-day evaluation is therefore the only
  vendor-sanctioned path that works unattended, and a container that is
  destroyed each run never reaches day 31 — worth agreeing with each vendor
  rather than assuming, and WireFlow are the ones to ask about a build-server
  licence.
- **Licensing is now genuinely settled, and it is not the project's 1394.** With
  every vendor's shipped `.lf` seeded, the same project run reports
  **254 of 1648** and **zero** `Bad License` lines, against 251–252 before. So
  the licence gating was real, is fixed, and accounts for about two of the
  project's own VIs — the 199 it unbroke are all inside
  `vi.lib\addons\WireFlow`. Keep the seeding: it is correct, it is cheap, and it
  removes a whole class of false diagnosis. But stop treating licensing as a
  candidate explanation for the bulk. `vi.lib\GPower` — also TPLAT-licensed —
  analysed **1163 of 1163 passing** even before this, so the container was never
  globally broken for licensed vendor libraries. The measurement still worth
  taking is `vi.lib\SEF Energy` with the licences seeded: it was 697 of 946, and
  63 of its failures were in the WireFlow-dependent `fs-net-com`, so that number
  should move even though the project's did not.
- **The per-user LabVIEW configuration is exhausted too: 252, byte-identical.**
  This was the last dimension no replication had touched. Copying the whole of
  `Documents\LabVIEW Data` (1219 files, 10.8 MB, caches excluded) into the
  container user's profile and patching `neverShowAddonLicensingStartup=True`
  into `LabVIEW.ini` produces a report differing from the previous run only in
  its timestamp. Note where these live, because two of them are easy to miss:
  `LabVIEW.ini` sits in the **install root**, which the replication never
  copied because it only ever walked named subdirectories; and `Documents` is
  OneDrive-redirected on this machine, so the 2026 per-user data is under
  `C:\Users\<user>\OneDrive\Documents\LabVIEW Data`, not `~\Documents`. The ini
  itself is 57 tokens of UI state plus `server.tcp.*`, so do not copy it
  wholesale — a host ini with VI Server disabled would break `LabVIEWCLI`.
  Nothing else there is a candidate: `AppData\Local\National Instruments` holds
  only the AI assistant ("Nigel") and NLS plugin caches, `AppData\Roaming` only
  FlexLogger. `ExtraVILib\ChannelInstances` looks promising — those are
  generated Channel Wire instances that LabVIEW writes per user rather than
  shipping in `vi.lib`, so they would be genuinely absent — but this project
  references none of them (0 files matching `ChannelInstances`, `Stream-c(`,
  `Tag-path` or `High Speed Stream-a`), so they belong to some other project.
- **Do not mount a OneDrive-redirected folder into a Windows container: every
  file arrives as zero bytes.** The container has no OneDrive filter driver, so
  it sees the reparse points and not the content — measured as 1219 files at
  10.76 MB on the host and the same 1219 files at 0 bytes through the mount,
  with `robocopy` reporting exit 8 and nothing obviously wrong otherwise. Stage
  such a directory to local disk on the host first, then mount the copy. Note
  the files are not cloud-only placeholders (no `Offline` or
  `RecallOnDataAccess` attribute on any of them), so checking for that
  attribute does not predict this.
- **Mass Compile on ONE library is the diagnostic that finally names things, and
  it is the tool to reach for first.** VI Analyzer only ever says "This VI is
  broken", which is why days went into measuring aggregates. Mass Compile logs
  the actual unresolved item and its caller:

  ```
  Search failed to find "niEioResolveResourceRelativePath.vi" previously from
    "<vilib>:\eio\utilities\niEioResolveResourceRelativePath.vi"
  Search failed to find "FS-NET.lvclass:FS-Net Config.ctl" previously from
    "..\..\Dropbox (Personal)\CG\Downing\.FS Utils\FS-NET\FS-Net Config.ctl"
    +=+ Caller: "Read Pads MQTT.vi"
  ```

  This does not contradict the note above that Mass Compile hangs on the
  project — it still does, re-measured at 45 minutes without even reaching
  `#### Starting Mass Compile`. The difference is not size but **location**: a
  library inside `vi.lib`, where its dependencies do exist, completes in about a
  minute (`fs-choke-actuator`, 52 VIs) and the whole of `vi.lib\SEF Energy`
  (850 VIs) in 8.8 minutes, whereas a single project module hangs exactly like
  the whole project does (`_Code\Valve`, 140 VIs, 20 minutes, no output). So the
  project carries references that send LabVIEW searching the disk and the
  installed libraries largely do not — which is itself worth knowing, and means
  this diagnostic only works against `vi.lib`. Point it at one library there,
  read the names, fix, repeat. Note it
  rewrites the VIs it compiles, so aim it at the container's own copy of
  `vi.lib` or at a throwaway copy of the project, never at `fsic2`.
- **The first named cause: `nilvfpgahostcomm` was missing, and adding it fixes
  the actuator libraries' unresolved dependency.** `<vilib>:\eio\utilities\...`
  resolves through the LVAddons merge, and `niEioResolveResourceRelativePath.vi`
  lives only in `LVAddons\nilvfpgahostcomm` (and its 32/64 twins) — not in
  `LabVIEW 2026\vi.lib`, so no amount of copying the LabVIEW folder could ever
  supply it. With the eight driver add-ons plus `nilvfpgahostcomm`, Mass Compile
  of `fs-choke-actuator` completes with **no** search failures and LabVIEW stays
  healthy. Adding the wider RIO family alongside it
  (`crio`, `rseries`, `nirio`, `fpgasr`, `rio_pt` and their bitness twins)
  brings back the wedge — VI Server listens but `LabVIEWCLI` gets `-350000` —
  so add `nilvfpgahostcomm` alone and bisect before adding more.
- **Some of these dependencies are missing on the developer's machine too, so
  the container is faithfully reproducing a broken install.** Of the items
  `vi.lib\SEF Energy` fails to resolve, `vi.lib\FS Configure` does not exist on
  the host at all and `vi.lib\SEF Energy\FS Utils\GPS Receiver` is an **empty
  directory** there, its `GPS Receiver.lvlib` absent. One reference is worse
  than missing: `Read Pads MQTT.vi`, installed under `vi.lib`, still points at
  `..\..\Dropbox (Personal)\CG\Downing\.FS Utils\FS-NET\FS-Net Config.ctl` —
  a saved link out of `vi.lib` into the developer's own working copy, which is
  unresolvable anywhere but his machine and is not even valid there now. Before
  blaming the container for a broken dependency, check whether the file exists
  on the host.
- **The broken libraries are the Actor Framework ones, but the Actor Framework
  is not the cause.** The correlation is near-perfect — `fs-net-com` (83 AF
  references, 63 of 70 broken), `fs-tx-actuator` (78, 33 of 69),
  `fs-choke-actuator` (61, 51 of 52), `fs-daq-logger` (51, 51 of 53),
  `fs-vx-actuator` (43, 24 of 40), against `FS Utils` (0 AF, 23 of 245) and
  `IP Camera` (0 AF, 2 of 89) — but `vi.lib\ActorFramework` itself analyses
  **131 of 131 clean** in the container. The AF libraries are simply the
  networked, hardware-facing ones. Note the stock image ships 144 AF files to
  the host's 156, the difference being the `Proxy Actor`, `Upper Proxy Actor`
  and `Lower Proxy Actor` directories, but `Actor Framework.lvlib` is
  byte-identical between the two and declares none of them, so that gap is not
  a break either.
- **Within a broken library, look at which VIs pass.** In `fs-choke-actuator`
  the single passing VI is `Scale Choke.vi`, pure computation, while every data
  accessor (`Write Config.vi`, `Write Set Point.vi`) and every message `Do.vi`
  fails — the signature of a broken class private data control rather than a
  broken subVI. Remember VI Analyzer only analyses VIs, so a broken `.ctl`
  never appears in the report while breaking everything that uses it.
- **`LabVIEWCLI` writing to stderr aborts the harness *after* the report is
  written.** With `$ErrorActionPreference = 'Stop'`, PowerShell turns the CLI's
  `Operation output:` on stderr into a terminating `NativeCommandError`, so the
  script dies before printing the report header and the run looks like a failed
  analysis. Check `C:\out\` before believing that — the analysis had completed
  and the report was complete. For the same reason, patch `LabVIEW.ini` through
  its raw text rather than `Add-Content`: if the file lacks a trailing newline,
  `Add-Content` appends the new token onto the end of the last one, which here
  would silently corrupt a `server.tcp.*` setting.
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
- **JKI support containers on Linux only, and their documented setup has three
  steps we never took.** VIPM 2026 Q3 does ship a real standalone CLI (Rust, not
  a wrapper around the desktop app) with a
  [Docker guide](https://docs.vipm.io/2026-Q3/cli/docker/), but the single
  official example is `FROM nationalinstruments/labview:2026q1-linux` with an
  Xvfb display script, and the guide's LabVIEW-launch instructions are marked
  "Linux only". There is no Windows-container example anywhere in their
  materials, and they say plainly that "LabVIEW containers are new ... expect
  these setup steps to simplify". Before concluding anything further about the
  Windows crash, note what their guide requires that `install-vipc.ps1` does
  not do: `vipm activate --serial-number ... --name ... --email ...`, described
  as **"Activate VIPM Pro (required today)"** — which cuts against the earlier
  note here that licensing was eliminated, since that was inferred from
  `vipm about` reporting Free Edition with a valid code and we have never
  actually activated; `VIPM_NONINTERACTIVE=1`, to stop commands waiting on input
  nobody can supply; and `vipm install --labview-version` plus
  `--labview-bitness`, which the guide calls for whenever the image holds more
  than one LabVIEW — and this image holds **four** (2023, 2024, 2025, 2026).
  Also `vipm refresh` before each install.
- **JKI Dragon cannot help inside a container.** It is a desktop GUI for opening
  a project in the right LabVIEW version with the right packages, installed at
  `C:\Program Files\JKI\Dragon` (2026.3.0 here). Its folder holds no CLI — one
  `JKI Dragon.exe` plus four support executables (`exit-dragon`, `post-install`,
  `registry-updater`, `update-helper`) — and the main binary carries LabVIEW
  runtime markers, so it is another LabVIEW-built application, the exact class of
  binary that dies with `0xC0000005` here. Its value is on a developer machine or
  a persistent Windows runner, where it would provision the tree that then gets
  replicated, not as a route into the image.
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
