# Handoff — FSCICD / FS iControl container validation

Copy everything below the line into a new agent chat to continue.

---

You are continuing work on **FSCICD**, a CI/CD system for LabVIEW, at:

```
C:\Users\kuehn\Dropbox (Personal)\CG\Downing\fscicd
```

Read `AGENTS.md` first (especially the 2026-09-28 remeasure bullet and the
VIPM / TPLAT / actor-hierarchy findings). Do not re-run experiments it marks
settled.

## HARD CONSTRAINTS

1. NEVER modify, move, or write to
   `C:\Users\kuehn\Dropbox (Personal)\CG\Downing\FS iControl`. Stage with
   `robocopy` to `C:\temp\fsic` and analyse the copy only. Mass Compile rewrites
   VIs — never aim it at the Dropbox tree.
2. All LabVIEW / LabVIEWCLI / VIPM execution is **inside Docker**. Never invoke
   them on the host.
3. Bitbucket is the code of record; agents push branches/PRs on **GitHub**
   (`github.com/jordankuehn/FSCICD`). Do not reintroduce a mirror or GitHub
   Actions workflow.
4. Keep committed `.ps1` files pure ASCII (no em-dashes).

## Current state (2026-09-28)

Environment is solved. The remaining failures are **source / package** problems
in the Actor hierarchy, not missing container files.

| Image | Use? |
|---|---|
| `fscicd-labview:2026q3-windows-vipm` | **Yes** — working measurement image |
| `fscicd-labview:2026q3-windows` | **No** — LabVIEWCLI `-350000` after VIPM bake |
| `fscicd-labview:2026q3-windows-replica` | **No** — poisoned registry hives |
| `fscicd-labview:staging` | OK for ad-hoc probes with `replicate-in-container.ps1` |

### Latest VI Analyzer numbers

Host `vi.lib\SEF Energy` packages edited 2026-09-28 ~13:28–13:36 were staged to
`C:\temp\patch\SEF Energy` and overlaid into the container before both runs
(verified 0s skew vs host).

| Target | Score | Notes |
|---|---|---|
| Project (`C:\temp\fsic`) | **189 / 1510** | Was 244/1647 on vipm-bake; Actor modules still 100% fail |
| `vi.lib\SEF Energy` | **783 / 1074** | `fs-tx-actuator`, `fs-vx-actuator`, `fs-systemlink` clean; choke / daq-logger / net-com still wall |

Reports: `C:\temp\out\report-remeasure.txt`, `report-sef-remeasure.txt`.
Scripts: `C:\temp\diag\via-remeasure.ps1`, `via-sef-remeasure.ps1`.

After every fresh `robocopy` of the project, restore
`C:\temp\diag\FSiC VI Analyzer Tests.viancfg` →
`C:\temp\fsic\_Code\` (it is not in the Dropbox checkout).

### Still broken (IDE work, not container work)

Open these on the **developer machine**, read Ctrl+L, fix, resave, then
re-overlay host `vi.lib` (or re-bake) and remeasure:

1. `vi.lib\SEF Energy\fs-daq-logger` — accessors `Read local DAQ Queue 2.vi`,
   `Write local DAQ Queue.vi` (saved `bad node`, LV 23.0) → 51/53 fail.
2. `vi.lib\SEF Energy\fs-choke-actuator` — `Actor Core.vi` / `Handle Error.vi`
   → 51/52 fail (Mass Compile of the library is clean; breakage is inside
   class private data / types).
3. `vi.lib\SEF Energy\fs-net-com` — callers expect unprefixed
   `FS-NET.lvclass:...` while the class is `FS-NET.lvlib:FS-NET.lvclass`; also
   absolute-path rot in `Pub Status.vi` / `Rx FSV Status.vi` / `oldInit.vi`
   → 63/70 fail.
4. `FS Valve Interface` — 102/120 fail; stale type refs to actuators even
   where actuators now analyse clean.

Until those three packages unbreak, every project `Actor.lvclass` descendant
stays broken under headless VIA/Mass Compile.

### Repo / image notes for the next bake

- VIPM installs **work** when memory ≥2.5 GB (`-m 8GB`), `LV_RTE_HEADLESS`
  cleared for the install process tree, JKI `Settings.ini` year/quarter split,
  and `vipm refresh --force` first. See `docker/vipm/install-vipc.ps1` and
  `docker/README.md`.
- The committed tag `fscicd-labview:2026q3-windows` is still the broken
  post-install image; working tree was hand-assembled as
  `2026q3-windows-vipm`. Next successful `install-vipc.ps1` commit should
  replace `2026q3-windows` only after LabVIEWCLI connects (port 3363 + a real
  MassCompile/VIA probe).
- Seed TPLAT evaluation licences with `docker/seed-eval-licences.ps1` (as-shipped
  `.lf` into `Partners`, never the host-activated copy).
- Mass Compile diagnostic helper: `docker/masscompile-dir.ps1` (vi.lib-scoped
  only; 11–18 min silent load is normal).

## Suggested next steps

1. Confirm on the host IDE that choke / daq-logger / net-com VIs listed above
   are fixed (or still broken) — Ctrl+L is the ground truth.
2. If fixed: refresh `C:\temp\patch\SEF Energy` from host `vi.lib`, re-run
   `via-sef-remeasure.ps1` then `via-remeasure.ps1` on
   `fscicd-labview:2026q3-windows-vipm`.
3. If SEF packages pass and the project still fails: Mass Compile one project
   module from a throwaway copy (not Dropbox) and read Search-failed lines —
   likely remaining checkout link rot.
4. Only after project VIA is clearly past the ~250 ceiling: point
   `examples/fscicd.yml` / app-repo template at the working image tag and wire
   the Windows Bitbucket runner step.
5. Do **not** chase further mount/registry/LVAddons permutations — those
   dimensions are closed in `AGENTS.md`.

## Remeasure recipe (copy-paste)

```powershell
# stage project (read-only source)
robocopy "C:\Users\kuehn\Dropbox (Personal)\CG\Downing\FS iControl" C:\temp\fsic /MIR /XD .git /NFL /NDL /NJH /NJS /NP
Copy-Item "C:\temp\diag\FSiC VI Analyzer Tests.viancfg" "C:\temp\fsic\_Code\" -Force

# stage today's host packages
$src = "C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy"
$dst = "C:\temp\patch\SEF Energy"
# robocopy each edited package into $dst, then:
docker run --rm --name fscicd-remeasure -m 8GB `
  -v "C:\temp\diag:C:\bin" -v "C:\temp\patch:C:\patch" `
  -v "C:\temp\fsic:C:\work" -v "C:\temp\out:C:\out" `
  -e LV_RTE_HEADLESS=1 `
  fscicd-labview:2026q3-windows-vipm `
  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\bin\via-remeasure.ps1
```
