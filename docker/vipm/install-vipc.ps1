<#
.SYNOPSIS
    Installs every .vipc found in C:\vipm into the image's LabVIEW, at build time.

.DESCRIPTION
    Adapted, with the author's permission, from install-vipc.ps1 in Elijah
    Kerry's LabVIEW-CI-with-Containers
    (https://github.com/elijah286/LabVIEW-CI-with-Containers). Nearly every
    non-obvious step below exists because that project hit the failure it
    prevents; the comments say which.

    Scope is deliberately narrower than the original: it applies a project's own
    dependency configuration and nothing else. It installs no CI tooling of its
    own and treats every package as required, because a project VI that cannot
    resolve its subVIs is not analyzable.

.NOTES
    Environment overrides:
      LABVIEW_VERSION   LabVIEW year to target. MUST match the base image.
      LABVIEW_BITNESS   LabVIEW bitness to target. Default 64.
      VIPM_TIMEOUT      Per-operation timeout in seconds. Default 900.
      VIPM_ALLOW_MISSING_PACKAGES=1
                        Warn instead of failing when a package will not install.
                        For diagnosis only: the resulting image analyses a
                        project whose dependencies are incomplete, which reports
                        breakage that says nothing about the code.
      VIPM_RUN_PREFLIGHT=1
                        Run the (diagnostic-only) VIPM File Handler probe. Off
                        by default: it does not predict install failure, and
                        running it against a live engine can wedge the engine.
      VIPM_BATCH_SIZE   Packages per install chunk (default 10). A single
                        144-file batch timed out at 874 s; chunks keep each
                        VIPM_TIMEOUT window useful.
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# Overridable so the run-and-commit build can work in a container-local
# directory: extracting a bundled configuration writes hundreds of megabytes,
# which should not land in a bind-mounted source tree.
$VipcDir        = if ($Env:VIPC_DIR) { $Env:VIPC_DIR } else { 'C:\vipm' }
$LabVIEWVersion = if ($Env:LABVIEW_VERSION) { $Env:LABVIEW_VERSION } else { '2026' }
$LabVIEWBitness = if ($Env:LABVIEW_BITNESS) { $Env:LABVIEW_BITNESS } else { '64' }

# The CLI is non-interactive by default; these keep it that way and make its
# failures legible in a build log.
$Env:VIPM_NONINTERACTIVE = '1'
$Env:VIPM_ASSUME_YES     = '1'
$Env:NO_COLOR            = '1'
# VIPM_DEBUG is deliberately NOT defaulted on: the working configuration was
# measured without it, and every difference from that configuration has at some
# point turned out to matter.

# VIPM_COMMUNITY_EDITION is deliberately NOT set. Forcing it turns on VIPM's
# public-Git-repository entitlement gate, which fails inside a sealed build
# layer with exit 6. Left unset, the CLI still runs as Community Edition and
# installs without a Pro licence.

# Explicit timeouts rather than CI=true env hints (the hints change other CLI
# behaviour too, and the measured-working configuration ran without them). The
# liveliness timeout matters separately from the operation timeout: a first
# install into a cold headless LabVIEW can sit silent well past the CLI's 60 s
# default while LabVIEW mass compiles the package, and the CLI then reports
# "made no progress" and gives up on an install that was working.
if (-not $Env:VIPM_TIMEOUT)   { $Env:VIPM_TIMEOUT = '900' }
if (-not $Env:VIPM_DESKTOP_LIVELINESS_TIMEOUT) { $Env:VIPM_DESKTOP_LIVELINESS_TIMEOUT = '900' }

# The VIPM Desktop engine is itself a LabVIEW-runtime app: under a global
# LV_RTE_HEADLESS=1 (which the NI base image bakes into ENV for CI-time
# LabVIEWCLI use) it runs but never completes the CLI's startup handshake, and
# every operation dies at "wait for VIPM startup". Clearing it here affects only
# this process tree; the image ENV that runtime workflows rely on is untouched.
# (LCWC hit the same failure for three weeks in Aug 2026 - see their docs, s.15.)
if ($Env:LV_RTE_HEADLESS) {
    Write-Host "Clearing LV_RTE_HEADLESS=$($Env:LV_RTE_HEADLESS) for the VIPM install."
    Remove-Item Env:LV_RTE_HEADLESS -ErrorAction SilentlyContinue
}

# The engine's package-list refresh alone peaks over 1.3 GB on LabVIEW 2026 Q3,
# and a memory-capped container (hyperv-isolated Windows containers default to
# 1 GB) starves it into the identical "wait for VIPM startup" wedge. Fail fast
# with the fix rather than spending three 15-minute timeouts learning it.
$visibleGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1MB, 1)
Write-Host "Container visible memory: $visibleGB GB"
if ($visibleGB -lt 2.5 -and $Env:VIPM_ALLOW_LOW_MEMORY -ne '1') {
    throw ("Only $visibleGB GB of memory is visible in this container, and the VIPM stack " +
           '(headless LabVIEW + VIPM Desktop engine + CLI) needs well over 2 GB - the engine ' +
           'will hang at "wait for VIPM startup". Re-run with docker run -m 8GB (hyperv-isolated ' +
           'Windows containers default to 1 GB), or set VIPM_ALLOW_LOW_MEMORY=1 to proceed anyway.')
}

# --- Locate the VIPM CLI -----------------------------------------------------
# Prefer the modern CLI (JKI\VIPM) over the legacy LabVIEW-based one, which has
# no usable headless mode.
$VipmDir = 'C:\Program Files\JKI\VI Package Manager'
$VipmExe = @(
    'C:\Program Files\JKI\VIPM\vipm.exe',
    'C:\Program Files (x86)\JKI\VIPM\vipm.exe',
    (Join-Path $VipmDir 'vipm.exe'),
    (Join-Path $VipmDir 'support\vipm.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $VipmExe) {
    throw ('The VIPM CLI was not found in this image. The base image is expected to provide it; ' +
           'see docker/labview-worker.windows.Dockerfile for the base being used.')
}
Write-Host "Using VIPM CLI: $VipmExe"

# --- Locate LabVIEW ----------------------------------------------------------
$LabVIEWExe = @(
    'C:\Program Files\National Instruments',
    'C:\Program Files (x86)\National Instruments'
) | Where-Object { Test-Path $_ } |
    ForEach-Object { Get-ChildItem -Path $_ -Directory -Filter 'LabVIEW*' -ErrorAction SilentlyContinue } |
    ForEach-Object { Join-Path $_.FullName 'LabVIEW.exe' } |
    Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $LabVIEWExe) { throw 'LabVIEW.exe was not found in this image.' }
Write-Host "Using LabVIEW: $LabVIEWExe"

# --- Seed VIPM's settings ----------------------------------------------------
# The CLI reads Settings.ini for its target LabVIEW and aborts with "IO error:
# Failed to load ... (os error 2)" when it is absent. In a fresh image VIPM has
# never been launched interactively, so it never exists.
$VipmSettingsDir = 'C:\ProgramData\JKI\VIPM'
$VipmSettings    = Join-Path $VipmSettingsDir 'Settings.ini'

$script:LabVIEWTargetVersion = '{0}.{1} ({2}-bit)' -f
    (Get-Item $LabVIEWExe).VersionInfo.ProductMajorPart,
    (Get-Item $LabVIEWExe).VersionInfo.ProductMinorPart,
    $LabVIEWBitness

# The quarter identifies the target everywhere. An earlier revision put the
# YEAR (26.0) in "Versions 0" and the quarter in "Active Target.Version",
# following JKI's guidance in vipm-io/vipm-desktop-issues#126 - but the engine
# looks the active target up in the [Targets] list by version, and a mismatched
# pair leaves its installs sitting at "0.0% - Connecting to LabVIEW" forever.
# The quarter in BOTH is the form LCWC's working Windows bakes use; CLI
# auto-detection is covered by passing --labview-version/--labview-bitness
# explicitly on every install (see $GlobalFlags).

function Test-VipmSettings {
    <#
        A file existing is not enough. Something in the VIPM stack creates a
        ZERO-BYTE Settings.ini, and a plain Test-Path is satisfied by it - so
        the seeding below used to be skipped, leaving the CLI with no LabVIEW
        target to attach to. Require content, and require the target entry.
    #>
    if (-not (Test-Path $VipmSettings)) { return $false }
    if ((Get-Item $VipmSettings).Length -eq 0) { return $false }
    $raw = Get-Content -Path $VipmSettings -Raw
    if ($raw -notmatch 'Active Target\.Name') { return $false }
    # A file from the old seeding (year in "Versions 0", quarter in the active
    # target) leaves the engine unable to find its target; re-seed it.
    return ($raw -match [regex]::Escape('Versions 0="' + $script:LabVIEWTargetVersion + '"'))
}

function Set-VipmSettings {
    param([string] $Because)

    # The INI wants the executable as "/C/Program Files/.../LabVIEW.exe".
    $lvIniPath = '/' + (($LabVIEWExe -replace ':', '') -replace '\\', '/')

    # Key set and conventions from LCWC's working Windows bakes (their
    # install-vipc.ps1), plus JKI's container guidance in
    # vipm-io/vipm-desktop-issues#126:
    #
    #   * The QUARTER version (26.3) goes in "Versions 0" AND
    #     "Active Target.Version" - see the comment above Set-VipmSettings.
    #   * "LVTN TOS Agreed MD5" pre-accepts the LabVIEW Tools Network terms.
    #     Unaccepted terms are one of the things that can leave a GUI-less VIPM
    #     waiting on a dialog nobody can see.
    #
    # The [General] suppressions exist for the same reason: an update check or
    # a download warning has no one to answer it in a container.
    $settings = @"
[General]
check for updates on startup?="FALSE"
Check new ver. of App. on startup?="FALSE"
Suppress Download warning?="TRUE"
Mass Compile After Package Install?="FALSE"
IsFirstLaunch="FALSE"

[Targets]
Names.<size(s)>="1"
Names 0="LabVIEW"
Versions.<size(s)>="1"
Versions 0="$script:LabVIEWTargetVersion"
Locations.<size(s)>="1"
Locations 0="$lvIniPath"
Ports="<size(s)=1> 3363"
Tested.<size(s)>="1"
Tested 0="TRUE"
Disabled.<size(s)>="1"
Disabled 0="FALSE"
Connection Timeout="120"
Active Target.Name="LabVIEW"
Active Target.Version="$script:LabVIEWTargetVersion"
PingDelay(ms)="-1"
PingTimeout(ms)="60000"
CommunityEdition.<size(s)>="1"
CommunityEdition 0="TRUE"

[Repository]
LVTN TOS Agreed MD5="5fac0d1abca8865f3ac38e1dee806526"
"@
    New-Item -ItemType Directory -Path $VipmSettingsDir -Force | Out-Null
    Set-Content -Path $VipmSettings -Value $settings -Encoding ASCII
    Write-Host "Seeded VIPM Settings.ini ($Because) targeting LabVIEW $script:LabVIEWTargetVersion"
}

if (Test-VipmSettings) {
    Write-Host "VIPM Settings.ini already targets a LabVIEW; leaving it alone."
} else {
    $because = if (Test-Path $VipmSettings) { 'present but empty or untargeted' } else { 'absent' }
    Set-VipmSettings $because
}

# From here native VIPM commands write progress to stderr; control flow is
# driven off exit codes instead.
$ErrorActionPreference = 'Continue'

& $VipmExe --version 2>&1 | Out-Host

# --- The VIPM stack ----------------------------------------------------------
# The CLI does not install anything itself. It needs two other things running:
# LabVIEW, and the VIPM engine ("VI Package Manager.exe", which the CLI's own
# diagnostics call "VIPM Desktop"). Neither is running in a fresh container, so
# both are started here. Without a live LabVIEW the CLI fails with "IO error:
# Failed to load".
#
# The engine must be started BY THE CLI, never pre-launched here - see
# Start-VipmEngine for the measurement.

function Start-HeadlessLabVIEW {
    Write-Host 'Launching headless LabVIEW for VIPM ...'
    Start-Process -FilePath $LabVIEWExe -ArgumentList '--headless' | Out-Null
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect('127.0.0.1', 3363)
            if ($client.Connected) {
                $client.Close()
                Write-Host '  VI Server is ready on port 3363.'
                return
            }
        } catch { Start-Sleep -Seconds 3 }
    }
    Write-Warning '  Timed out waiting for the VI Server; continuing anyway.'
}

function Start-VipmEngine {
    # Deliberately does NOT pre-launch "VI Package Manager.exe". A manually
    # started engine is the difference between wedging and working here: with a
    # pre-launched engine, `vipm refresh --force` times out at "wait for VIPM
    # startup" (measured twice, 2026-09-22, LCWC base image); with the CLI left
    # to start the engine itself, the identical refresh completed in under two
    # minutes, four times out of four. The CLI evidently needs to observe the
    # engine's own startup signal, which an already-running engine never emits.
    $running = Get-Process -Name 'VI Package Manager' -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host 'VIPM engine is already running; the CLI will attach or restart it as it sees fit.'
    } else {
        Write-Host 'VIPM engine not started here on purpose - the CLI starts it itself (pre-launching it wedges the handshake).'
    }
}

function Test-VipmFileHandler {
    <#
        The CLI does not talk to VIPM over a socket. It launches
        "VIPM File Handler.exe" with a command name and a pair of temp files:

            VIPM File Handler.exe -- /command:vipm_status
                /progress_file:<tmp> /return_file:<tmp>

        and polls for the return file. In NI's 2026 Windows container that
        helper dies with 0xC0000005 two seconds in, before creating either
        file, so the CLI polls a file that will never appear and every call
        ends as "Operation 'wait for VIPM startup' timed out" - after the full
        timeout, three times over if engine restarts are enabled.

        Test the hop directly instead. It costs seconds and it names the real
        failure, which no amount of waiting will.
    #>

    # Opt-in only. Beyond being a poor predictor (see below), running this probe
    # against an already-running engine appears to WEDGE the engine: it submits
    # a command that never completes (LVStatus.txt logs a recursive LEIF load
    # inside the helper), and the engine seems to process commands serially, so
    # the following refresh starves at "wait for VIPM startup". Measured
    # 2026-09-22 in the LCWC base image: with this probe, refresh timed out at
    # 900 s twice; without it, the identical refresh completed in under 2 min
    # four times out of four.
    if ($Env:VIPM_RUN_PREFLIGHT -ne '1') {
        Write-Host 'Skipping the VIPM File Handler probe (set VIPM_RUN_PREFLIGHT=1 to run it; it can wedge the engine).'
        return
    }

    $handler = @(
        (Join-Path $VipmDir 'support\VIPM File Handler.exe'),
        'C:\Program Files (x86)\JKI\VI Package Manager\support\VIPM File Handler.exe'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $handler) {
        Write-Warning 'VIPM File Handler.exe was not found; skipping the preflight.'
        return
    }

    $stem     = [guid]::NewGuid().ToString('N').Substring(0, 12)
    $progress = Join-Path $Env:TEMP "fscicd-prog-$stem"
    $ret      = Join-Path $Env:TEMP "fscicd-ret-$stem"
    $status   = Join-Path $Env:TEMP 'LVStatus.txt'
    Remove-Item $status -Force -ErrorAction SilentlyContinue

    Write-Host 'Preflight: asking VIPM File Handler for status ...'
    $proc = Start-Process -FilePath $handler -PassThru -ArgumentList @(
        '--', '/command:vipm_status', "/progress_file:$progress", "/return_file:$ret"
    )
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not $proc.HasExited) { Start-Sleep -Seconds 2 }

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Write-Host '  The helper was still running after 60s; treating that as usable.'
        return
    }

    if (Test-Path $ret) {
        Write-Host "  The helper answered (exit $($proc.ExitCode)); the VIPM stack is reachable."
        return
    }

    # No return file. This was once treated as fatal, but it is NOT load-bearing:
    # in a container where this exact probe fails, the CLI's own operations
    # (refresh, library add, package_set_install) complete once the stack is set
    # up per the recipe above - measured 2026-09-22, oglib_boolean installed
    # end-to-end with this helper still answering nothing. Whatever IPC the
    # helper exercises is not the one the modern CLI depends on. Warn and carry
    # on; the real verdict comes from the installs themselves.
    $detail = if ($proc.ExitCode -eq -1073741819) {
        'crashed with 0xC0000005 (access violation)'
    } else {
        "exited with code $($proc.ExitCode) without answering"
    }
    $lvStatus = if (Test-Path $status) {
        ' LabVIEW logged: ' + ((((Get-Content $status -Raw) -split "`r?`n") |
            Where-Object { $_.Trim() }) -join ' | ')
    } else { '' }

    Write-Warning ("The VIPM File Handler $detail. This helper's failure does not predict " +
                   "install failure (the modern CLI does not depend on it); continuing.$lvStatus")
}

# A cold engine occasionally never completes its startup handshake and stays
# wedged, turning every later call into another full timeout. Detect that and
# rebuild the stack, bounded so a genuinely broken engine still fails fast.
$script:EngineWedged   = $false
$script:RestartsUsed   = 0
$script:MaxRestarts    = if ($Env:VIPM_MAX_ENGINE_RESTARTS -match '^\d+$') { [int]$Env:VIPM_MAX_ENGINE_RESTARTS } else { 2 }

function Restart-VipmStack {
    Write-Warning ("  VIPM engine wedged; restarting the stack (attempt $($script:RestartsUsed)/$($script:MaxRestarts)) ...")
    foreach ($name in @('vipm', 'VI Package Manager', 'LabVIEW', 'LabVIEWCLI')) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 10   # let port 3363 and the file locks clear
    Start-HeadlessLabVIEW
    Start-VipmEngine
    $script:EngineWedged = $false
}

# --labview-version / --labview-bitness are GLOBAL options and must precede the
# subcommand. Some CLI builds reject that position with exit 2, so fall back to
# the bare form, which targets the active LabVIEW from Settings.ini.
$GlobalFlags = @('--labview-version', $LabVIEWVersion, '--labview-bitness', $LabVIEWBitness)

function Invoke-VipmOnce {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Targets)
    $out = & $VipmExe @GlobalFlags install @Targets 2>&1
    $out | Out-Host
    if ($LASTEXITCODE -eq 2) {
        Write-Host '  (CLI rejected the global LabVIEW flags; retrying the bare form)'
        $out = & $VipmExe install @Targets 2>&1
        $out | Out-Host
    }
    $exit = $LASTEXITCODE
    # Flatten before matching: the console wraps at the buffer width and can
    # split the phrase that identifies a wedged engine.
    $script:LastOutput = ($out | Out-String -Width 8192)
    $flat = ($script:LastOutput -replace '\s+', ' ')
    if ($exit -eq 124 -or $flat -match 'wait for VIPM startup' -or $flat -match "operation '[^']*' timed out after") {
        $script:EngineWedged = $true
    }
    return $exit
}

function Invoke-Vipm {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Targets)
    $exit = Invoke-VipmOnce @Targets
    while ($script:EngineWedged -and $script:RestartsUsed -lt $script:MaxRestarts) {
        $script:RestartsUsed++
        Restart-VipmStack
        Write-Host '  Retrying after the engine restart ...'
        $exit = Invoke-VipmOnce @Targets
    }
    return $exit
}

# --- Package specs from a .vipc ---------------------------------------------
# config.xml names packages as '<name>-1.2.3.4'; `vipm install` wants
# '<name>@1.2.3.4', because the hyphen form is read as a file path. A trailing
# '-<build>' suffix is dropped; the dotted version resolves on its own.
function Get-VipcPackageSpecs([string] $VipcPath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $zip = [System.IO.Compression.ZipFile]::OpenRead($VipcPath)
    try {
        $entry = $zip.Entries | Where-Object { $_.Name -eq 'config.xml' } | Select-Object -First 1
        if (-not $entry) { return @() }
        $reader = New-Object System.IO.StreamReader($entry.Open())
        try { [xml]$config = $reader.ReadToEnd() } finally { $reader.Close() }
    } finally { $zip.Dispose() }

    $names = @($config.VI_Package_Configuration.Target.Package | ForEach-Object { $_.Name })
    return @(foreach ($name in $names) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        if ($name -match '^(?<n>.+)-(?<v>\d+(?:\.\d+)+)(?:-\d+)?$') { '{0}@{1}' -f $Matches.n, $Matches.v }
        else { $name.Trim() }
    })
}

# A .vipc that bundles its packages carries the .vip payloads inside the zip.
# Extracting them lets the installer reference the files directly, which is the
# only way to install a package published on no VIPM repository - an in-house
# library, for instance.
function Expand-BundledPackages([string] $VipcPath, [string] $Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $extracted = New-Object System.Collections.Generic.List[string]
    $zip = [System.IO.Compression.ZipFile]::OpenRead($VipcPath)
    try {
        foreach ($entry in $zip.Entries) {
            if ([System.IO.Path]::GetExtension($entry.Name) -ne '.vip') { continue }
            $target = Join-Path $Destination $entry.Name
            if (-not (Test-Path $target)) {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            }
            $extracted.Add($target)
        }
    } finally { $zip.Dispose() }
    return @($extracted.ToArray())
}

# --- Install -----------------------------------------------------------------
$vipcFiles = @(Get-ChildItem $VipcDir -Filter '*.vipc' -File)
if ($vipcFiles.Count -eq 0) { throw "No .vipc files found in $VipcDir." }

# Extract before anything else: whether a configuration bundles its payloads
# decides whether the resolver index is needed at all, and a refresh that has to
# reach the engine costs a full timeout when the engine is unwell.
$plan = @(foreach ($vipc in $vipcFiles) {
    [pscustomobject]@{
        Vipc    = $vipc
        Bundled = @(Expand-BundledPackages $vipc.FullName $VipcDir)
    }
})
foreach ($item in $plan) {
    if ($item.Bundled.Count -gt 0) {
        Write-Host "Extracted $($item.Bundled.Count) bundled package file(s) from $($item.Vipc.Name)."
    } else {
        Write-Host "$($item.Vipc.Name) bundles no package files; its packages must be resolved by name."
    }
}

Start-HeadlessLabVIEW
Start-VipmEngine
Test-VipmFileHandler

# Refresh ALWAYS, even when every package is bundled as a local file. This is
# not about the resolver index (local-file installs need none): the engine's
# library operations wedge at "wait for VIPM startup" until one refresh has
# completed, and work immediately afterwards - measured 2026-09-22 in the same
# container, "Adding 144 local packages" timed out at 900 s without a refresh
# and "Adding 1 local package" succeeded in seconds after one. A forced refresh
# also matters when the index IS needed: a plain refresh reports success while
# downloading nothing, leaving every by-name package "not found" (exit 3).
Write-Host 'Refreshing VIPM package sources (refresh --force) ...'
& $VipmExe refresh --force 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    # Refresh is the first real engine health check; a cold-start race gets one
    # stack restart before we conclude anything (LCWC does the same).
    Write-Warning "  Refresh failed (exit $LASTEXITCODE); restarting the VIPM stack and retrying once."
    $script:RestartsUsed++
    Restart-VipmStack
    & $VipmExe refresh --force 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "  Refresh failed again (exit $LASTEXITCODE); library operations will likely wedge."
    }
}

# Install a set of targets - either local .vip paths or name@version specs -
# in chunks, falling back to one at a time so the log names what failed.
# A single 144-file batch timed out at 874 s after a healthy refresh
# (2026-09-22); one package installs in seconds, so chunk size is the lever.
# Returns the targets that did not install.
function Install-Targets {
    param([string[]] $Targets, [string] $Label)

    if (-not $Targets -or $Targets.Count -eq 0) { return @() }

    $batchSize = if ($Env:VIPM_BATCH_SIZE -match '^\d+$' -and [int]$Env:VIPM_BATCH_SIZE -gt 0) {
        [int]$Env:VIPM_BATCH_SIZE
    } else { 10 }

    $failures = New-Object System.Collections.Generic.List[string]
    $total = $Targets.Count
    for ($offset = 0; $offset -lt $total; $offset += $batchSize) {
        $end = [Math]::Min($offset + $batchSize, $total) - 1
        $chunk = @($Targets[$offset..$end])
        $n = $chunk.Count
        Write-Host ("  Installing {0} {1} (items {2}-{3} of {4}) ..." -f $n, $Label, ($offset + 1), ($end + 1), $total)
        # One attempt per chunk - retrying a timed-out 10-pack burns another
        # full VIPM_TIMEOUT; fall through to one-at-a-time instead.
        if ((Invoke-VipmOnce @chunk) -eq 0) { continue }

        Write-Host '  Chunk failed; retrying those packages one at a time ...'
        if ($script:EngineWedged -or $script:RestartsUsed -lt $script:MaxRestarts) {
            $script:RestartsUsed++
            Restart-VipmStack
        }
        foreach ($target in $chunk) {
            if ((Invoke-Vipm $target) -ne 0) {
                $name = if (Test-Path $target) { Split-Path $target -Leaf } else { $target }
                Write-Warning "  FAILED: $name"
                $failures.Add($target)
            }
        }
    }
    return @($failures.ToArray())
}

$failed = @()
foreach ($item in $plan) {
    $vipc    = $item.Vipc
    $bundled = $item.Bundled
    Write-Host ''
    Write-Host "=== Applying $($vipc.Name) ==="

    # Prefer the bundled package FILES over anything else. Installing from file
    # needs no resolver index, which matters because a refresh that fails leaves
    # every by-name install resolving as "not found"; and it is the only route
    # for a package published on no VIPM repository.
    if ($bundled.Count -gt 0) {
        $failed += Install-Targets $bundled 'bundled package file(s)'
        continue
    }

    # No bundled payloads: hand VIPM the configuration file. Deliberately a
    # single attempt - if this wedges the engine, retrying the identical call
    # only burns another full timeout, so fall through to package names instead.
    Write-Host '  No bundled payloads; installing from the configuration file ...'
    $exit = Invoke-VipmOnce '-y' $vipc.FullName
    if ($exit -eq 0 -and $script:LastOutput -match 'No packages were installed') {
        Write-Warning '  VIPM accepted the file but installed nothing; falling back to package names.'
        $exit = 42
    }
    if ($exit -eq 0) { continue }

    Write-Host "  Configuration-file install failed (exit $exit); installing by package name ..."
    $specs = @(Get-VipcPackageSpecs $vipc.FullName)
    if ($specs.Count -eq 0) {
        Write-Warning "  No package names could be read from $($vipc.Name)."
        $failed += $vipc.Name
        continue
    }
    $failed += Install-Targets $specs 'package(s) by name'
}

foreach ($name in @('vipm', 'VI Package Manager', 'LabVIEW')) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($failed.Count -gt 0) {
    $message = "$($failed.Count) package(s) or configuration(s) did not install: " + ($failed -join ', ')
    if ($Env:VIPM_ALLOW_MISSING_PACKAGES -eq '1') {
        Write-Warning ($message + ' VIPM_ALLOW_MISSING_PACKAGES=1 is set, so the build continues.')
        exit 0
    }
    # Failing the build is deliberate: an image with missing dependencies
    # reports breakage that says nothing about the code under analysis, which is
    # worse than no image at all.
    Write-Error ($message + ' Failing the build so CI cannot run against an image whose dependencies are incomplete.')
    exit 1
}

Write-Host ''
Write-Host 'All VIPM dependencies installed.'
