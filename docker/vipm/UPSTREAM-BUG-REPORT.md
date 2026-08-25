# Draft bug report for JKI

To file at <https://github.com/vipm-io/vipm-desktop-issues/issues>. Probably
related to #126 (same failure class, Linux side).

---

**Title:** VIPM File Handler crashes with 0xC0000005 in NI's 2026 Windows
container, so every CLI operation ends as "wait for VIPM startup" timed out

**Short description**

In NI's official LabVIEW 2026 Q3 **Windows** container, every `vipm install`
fails with `Operation 'wait for VIPM startup' timed out`. The cause is not a
slow or wedged engine: `VIPM File Handler.exe` crashes with `0xC0000005` two to
three seconds after launch, before writing its return file, so the CLI polls a
file that will never appear.

**Version information**

- VIPM Version: 2026.3.0, build 3954, build date 2026-06-18 (`vipm about`)
- VIPM CLI Version: 26.3.0
- Edition: Free, `Valid Activation Code: true`
- LabVIEW: 2026 Q3, 64-bit (`26.3f0`)
- OS: Windows Server 2022 Datacenter, build 20348.5256 (container)
- Base image: `nationalinstruments/labview:2026q3-windows`, via
  `ghcr.io/elijah286/labview-ci-with-containers-labview-base:2026`
- Virtualisation: Docker, Windows-container mode

**Steps to reproduce**

1. Start a container from a 2026 Q3 Windows LabVIEW image that includes VIPM.
2. Seed `C:\ProgramData\JKI\VIPM\Settings.ini` using the format recommended in
   #126 (Windows paths; `Versions 0="26.0 (64-bit)"`,
   `Active Target.Version="26.3 (64-bit)"`, `LVTN TOS Agreed MD5` present).
3. Start LabVIEW (`LabVIEW.exe --headless`) and `VI Package Manager.exe`, and
   let them settle.
4. Run `vipm --verbose --show-progress --timeout 90 install <any local .vip>`.

**Expected**

The package installs, or an error naming what is wrong.

**Actual**

```
Adding 1 local package to VIPM library...
[VIPM] Connecting to VIPM Desktop...
error: Failed to add packages to VIPM library: Operation 'wait for VIPM startup'
timed out after 89.9985516s
```

Invoking the helper the CLI uses, exactly as the CLI does (observed via
`Win32_Process` while an install was running):

```powershell
& 'C:\Program Files\JKI\VI Package Manager\support\VIPM File Handler.exe' `
    -- /command:vipm_status /progress_file:C:\Temp\p /return_file:C:\Temp\r
```

exits with `-1073741819` (`0xC0000005`) after 2 seconds and creates neither
file. `%TEMP%\LVStatus.txt`:

```
Recursive load during LEIF load! C:\Program Files\JKI\VI Package Manager\support\
VIPM File Handler.exe\JKI Reuse Pool\Windows\VIPM - Check is Windows Task
Runnning by Name (Scalar).vi is loading C:\Program Files\JKI\VI Package Manager\
support\VIPM File Handler.exe\JKI Reuse Pool\Windows\VIPM - Check is Windows
Task Runnning by Name (Scalar).vi\System
```

The crash log header records `#AppKind: AppLib`, `#AppRunMode: Headless`.

**Scope**

Other LabVIEW-built VIPM helpers fail identically:

| Executable | Result |
|---|---|
| `VIPM File Handler.exe` | `0xC0000005` |
| `VIPM Update Registry.exe` | `0xC0000005` |
| `LabVIEW Tools Network.exe` | `0xC0000005` |
| `JKIUpdate.exe` (not a LabVIEW app) | exit 0 |

**Already eliminated**

- **Engine health.** `VI Package Manager.exe` starts, stays alive, reports
  `Responding = True`, and holds no listening port (by design — the IPC is via
  files), so its health says nothing about the CLI's ability to reach it.
- **Slow first launch.** Watched for 8 minutes with periodic retries: engine idle
  at 3 s CPU, package index unchanged, installs still failing.
- **`Settings.ini`.** A seeded file survives an engine launch untouched. The
  zero-byte file we originally suspected is created by the failing CLI itself
  when the file is absent.
- **.NET.** Framework 4.8 (release 528449) is complete, and `System`,
  `System.Drawing`, `System.Windows.Forms` and `System.IO.Compression.FileSystem`
  all load from PowerShell in the same container.
- **Headless mode.** With `LV_RTE_HEADLESS` unset or `0` the helper exits cleanly
  instead of crashing, but still writes no return file, so installs hang either
  way.
- **`docker build` vs `docker run`.** Identical either way.
- **Local file vs by-name.** Both block on the same helper.
- **LabVIEWCLI.** Healthy in the same container (it reaches LabVIEW over VI
  Server on 3363 normally), so LabVIEW itself is fine.

**Impact**

There is no Windows fallback: NI publish no Windows image earlier than 2026
(`2026q1`, `2026q1patch1`, `2026q1patch2`, `2026q3`, `latest`), and the 2025
images reported working in #126 are Linux-only. Since a container's LabVIEW must
match the quarter the VIs were saved in, a 2026 Q3 project cannot move to an
older image. That leaves no supported way to install a project's VIPM
dependencies into a Windows CI container.

**Anything else**

Happy to run further diagnostics in this container, or to supply the full crash
logs and the `Settings.ini` in use.
