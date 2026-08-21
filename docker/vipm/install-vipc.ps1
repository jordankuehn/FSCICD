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
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$VipcDir        = 'C:\vipm'
$LabVIEWVersion = if ($Env:LABVIEW_VERSION) { $Env:LABVIEW_VERSION } else { '2026' }
$LabVIEWBitness = if ($Env:LABVIEW_BITNESS) { $Env:LABVIEW_BITNESS } else { '64' }

# The CLI is non-interactive by default; these keep it that way and make its
# failures legible in a build log.
$Env:VIPM_NONINTERACTIVE = '1'
$Env:VIPM_ASSUME_YES     = '1'
$Env:NO_COLOR            = '1'
if (-not $Env:VIPM_DEBUG) { $Env:VIPM_DEBUG = '1' }

# VIPM_COMMUNITY_EDITION is deliberately NOT set. Forcing it turns on VIPM's
# public-Git-repository entitlement gate, which fails inside a sealed build
# layer with exit 6. Left unset, the CLI still runs as Community Edition and
# installs without a Pro licence.

# VIPM shortens its timeouts when it does not believe it is in CI, and those
# desktop defaults can abort a cold headless LabVIEW mid-handshake.
if (-not $Env:CI)             { $Env:CI = 'true' }
if (-not $Env:GITHUB_ACTIONS) { $Env:GITHUB_ACTIONS = 'true' }
if (-not $Env:VIPM_TIMEOUT)   { $Env:VIPM_TIMEOUT = '900' }

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
if (-not (Test-Path $VipmSettings)) {
    $info = (Get-Item $LabVIEWExe).VersionInfo
    $targetVersion = '{0}.{1} ({2}-bit)' -f $info.ProductMajorPart, $info.ProductMinorPart, $LabVIEWBitness
    # The INI wants the executable as "/C/Program Files/.../LabVIEW.exe".
    $lvIniPath = '/' + (($LabVIEWExe -replace ':', '') -replace '\\', '/')
    $settings = @"
[General]
IsFirstLaunch="FALSE"

[Targets]
Names.<size(s)>="1"
Names 0="LabVIEW"
Versions.<size(s)>="1"
Versions 0="$targetVersion"
Locations.<size(s)>="1"
Locations 0="$lvIniPath"
Ports="<size(s)=1> 3363"
Tested.<size(s)>="1"
Tested 0="TRUE"
Disabled.<size(s)>="1"
Disabled 0="FALSE"
Connection Timeout="120"
Active Target.Name="LabVIEW"
Active Target.Version="$targetVersion"
CommunityEdition.<size(s)>="1"
CommunityEdition 0="TRUE"
"@
    New-Item -ItemType Directory -Path $VipmSettingsDir -Force | Out-Null
    Set-Content -Path $VipmSettings -Value $settings -Encoding ASCII
    Write-Host "Seeded VIPM Settings.ini targeting LabVIEW $targetVersion"
}

# From here native VIPM commands write progress to stderr; control flow is
# driven off exit codes instead.
$ErrorActionPreference = 'Continue'

& $VipmExe --version 2>&1 | Out-Host

# --- The VIPM stack ----------------------------------------------------------
# The CLI does not install anything itself: it delegates to the VIPM engine, a
# LabVIEW-runtime application. Neither the engine nor LabVIEW is running in a
# build layer, so both are started here. Without a live LabVIEW the CLI fails
# with "IO error: Failed to load"; without a pre-started engine it blocks on
# "wait for VIPM startup" until the whole timeout expires.
$script:VipmEngineExe = @(
    (Join-Path $VipmDir 'VI Package Manager.exe'),
    'C:\Program Files (x86)\JKI\VI Package Manager\VI Package Manager.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1

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
    if (-not $script:VipmEngineExe) { return }
    if (Get-Process -Name 'VI Package Manager' -ErrorAction SilentlyContinue) { return }
    Write-Host 'Pre-launching the VIPM engine so the CLI can attach ...'
    Start-Process -FilePath $script:VipmEngineExe | Out-Null
    Start-Sleep -Seconds 45
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
# only way to install a package published on no VIPM repository — an in-house
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

Start-HeadlessLabVIEW
Start-VipmEngine

# A plain refresh reports success while downloading nothing, leaving an empty
# resolver index so every package resolves as "not found" (exit 3).
Write-Host 'Refreshing VIPM package sources (refresh --force) ...'
& $VipmExe refresh --force 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Warning "  Refresh failed (exit $LASTEXITCODE); version-pinned installs may still resolve from cache."
}

$failed = @()
foreach ($vipc in $vipcFiles) {
    Write-Host ''
    Write-Host "=== Applying $($vipc.Name) ==="

    $bundled = @(Expand-BundledPackages $vipc.FullName $VipcDir)
    if ($bundled.Count -gt 0) {
        Write-Host "  Extracted $($bundled.Count) bundled package file(s) from the .vipc."
    }

    # Preferred path: hand VIPM the .vipc itself.
    Write-Host "  Installing from the configuration file ..."
    $exit = Invoke-Vipm '-y' $vipc.FullName
    if ($exit -eq 0 -and $script:LastOutput -match 'No packages were installed') {
        Write-Warning '  VIPM accepted the file but installed nothing; falling back to package-level installs.'
        $exit = 42
    }

    if ($exit -ne 0) {
        if ($script:EngineWedged) {
            Write-Warning "  The VIPM engine never came online; skipping $($vipc.Name)."
            $failed += $vipc.Name
            continue
        }
        # The engine is up but rejected the file-apply path (Code 42 and
        # friends). Installing package by package still works.
        Write-Host "  File install failed (exit $exit); installing package by package ..."
        $specs = @(Get-VipcPackageSpecs $vipc.FullName)
        if ($specs.Count -eq 0) {
            Write-Warning "  No package names could be read from $($vipc.Name)."
            $failed += $vipc.Name
            continue
        }

        Write-Host "  $($specs.Count) packages to install."
        $exit = Invoke-Vipm @specs
        if ($exit -ne 0) {
            Write-Host "  Batch install failed (exit $exit); retrying individually to identify the failures ..."
            foreach ($spec in $specs) {
                if ($script:EngineWedged) {
                    Write-Warning '  Engine wedged; abandoning the remaining packages.'
                    break
                }
                if ((Invoke-Vipm $spec) -ne 0) {
                    Write-Warning "  FAILED: $spec"
                    $failed += $spec
                }
            }
        }
    }
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
