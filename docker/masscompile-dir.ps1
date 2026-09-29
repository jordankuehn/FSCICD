<#
.SYNOPSIS
    Run Mass Compile on one or more directories inside a LabVIEW worker container.

.DESCRIPTION
    VI Analyzer only reports "This VI is broken". Mass Compile names the actual
    missing dependency or bad subVI - which is why this script exists.

    Mass Compile REWRITES every VI it compiles. Point it only at:

      - a library inside the container's own vi.lib (writable layer), or
      - a throwaway copy of a project (never the developer's source tree)

    Do not use this against a full project whose dependencies are missing -
    Mass Compile hangs there (see AGENTS.md). Use vi.lib-scoped libraries
    instead, e.g. vi.lib\SEF Energy\fs-net-com.

    By default the script seeds TPLAT evaluation licences first (same as the
    worker image install step) so licensed vendor libraries are not reported
    broken for licensing reasons.

.PARAMETER Directory
    Directory to compile. Overrides COMPILE_DIR when passed.

.PARAMETER Directories
    Semicolon-separated list of directories. Overrides COMPILE_DIRS when passed.

.PARAMETER LogPath
    Mass Compile log file for a single-directory run. Default C:\out\masscompile.log

.PARAMETER TimeoutMinutes
    Bound on each MassCompile invocation. Default 20.

.EXAMPLE
    # One library inside the worker image:
    docker run --rm -v C:\temp\out:C:\out -e LV_RTE_HEADLESS=1 `
      fscicd-labview:2026q3-windows powershell -NoLogo -NoProfile -ExecutionPolicy Bypass `
      -File C:\fscicd\masscompile-dir.ps1 `
      -Directory "C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-net-com"

.EXAMPLE
    # Several libraries in one LabVIEW session:
    docker run --rm -v C:\temp\out:C:\out -e LV_RTE_HEADLESS=1 `
      -e COMPILE_DIRS="C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-net-com;C:\Program Files\National Instruments\LabVIEW 2026\vi.lib\SEF Energy\fs-choke-actuator" `
      fscicd-labview:2026q3-windows powershell -NoLogo -NoProfile -ExecutionPolicy Bypass `
      -File C:\fscicd\masscompile-dir.ps1

.NOTES
    Environment overrides (used when parameters are not passed):
      COMPILE_DIR           single directory to compile
      COMPILE_DIRS          semicolon-separated directory list
      COMPILE_LOG           log path for a single-directory run
      COMPILE_MINUTES       per-run timeout in minutes (default 20)
      LABVIEW_VERSION       LabVIEW year (default 2026)
      VI_SERVER_PORT        VI Server TCP port (default 3363)
      SKIP_LICENCE_SEED=1   skip docker/seed-eval-licences.ps1
#>

[CmdletBinding()]
param(
    [string] $Directory,
    [string] $Directories,
    [string] $LogPath,
    [int]    $TimeoutMinutes = 0
)

$ErrorActionPreference = 'Stop'

function Get-LabVIEWPaths {
    $year = if ($Env:LABVIEW_VERSION) { $Env:LABVIEW_VERSION } else { '2026' }
    $dir = "C:\Program Files\National Instruments\LabVIEW $year"
    @{
        Year    = $year
        Root    = $dir
        Exe     = Join-Path $dir 'LabVIEW.exe'
        ViLib   = Join-Path $dir 'vi.lib'
    }
}

function Invoke-LicenceSeed {
    if ($Env:SKIP_LICENCE_SEED -eq '1') {
        Write-Host '=== skipping TPLAT licence seed (SKIP_LICENCE_SEED=1) ==='
        return
    }

    $seed = @(
        'C:\fscicd\seed-eval-licences.ps1',
        'C:\vipm\seed-eval-licences.ps1'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $seed) {
        Write-Warning 'seed-eval-licences.ps1 not found - licensed add-ons may look broken'
        return
    }

    Write-Host ''
    Write-Host "=== seeding TPLAT evaluation licences ($seed) ==="
    & $seed
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "seed-eval-licences.ps1 exited $LASTEXITCODE"
    }
}

function Wait-ViServer {
    param(
        [string] $LabVIEWExe,
        [int]    $Port,
        [int]    $StartupMinutes
    )

    Write-Host ''
    Write-Host "=== launching LabVIEW  ($(Get-Date -Format s)) ==="
    $t0 = Get-Date
    $proc = Start-Process -FilePath $LabVIEWExe -PassThru
    $deadline = $t0.AddMinutes($StartupMinutes)

    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            throw "LabVIEW exited with code $($proc.ExitCode) before VI Server came up"
        }
        if (@(netstat -ano | Select-String ":$Port\s" | Select-String 'LISTENING')) {
            $elapsed = ((Get-Date) - $t0).TotalMinutes
            Write-Host ('   VI Server listening on {0} after {1:N1} min' -f $Port, $elapsed)
            return $proc
        }
        Start-Sleep -Seconds 10
    }

    throw "VI Server did not listen on port $Port within $StartupMinutes min"
}

function Show-MassCompileSummary {
    param(
        [string] $LogFile,
        [int]    $MaxLines = 20
    )

    if (-not (Test-Path $LogFile)) {
        Write-Warning "   no log at $LogFile"
        return
    }

    $lines = Get-Content $LogFile -ErrorAction SilentlyContinue
    Write-Host ('   log: {0} ({1} lines)' -f $LogFile, $lines.Count)

    $lines | Where-Object { $_ -match 'MassCompile operation|Starting Mass Compile|Connection established' } |
        ForEach-Object { Write-Host ('      {0}' -f $_) }

    $search = @($lines | Where-Object { $_ -match 'Search failed' })
    Write-Host ('   Search failed: {0}' -f $search.Count)
    $search | Select-Object -First $MaxLines | ForEach-Object { Write-Host ('      {0}' -f $_) }

    $bad = @($lines | Where-Object { $_ -match '### Bad (VI|subVI):' })
    Write-Host ('   Bad VI/subVI:  {0}' -f $bad.Count)
    $bad | Select-Object -First $MaxLines | ForEach-Object { Write-Host ('      {0}' -f $_) }

    $compileErr = @($lines | Where-Object { $_ -match 'CompileFile: error' })
    Write-Host ('   CompileFile error: {0}' -f $compileErr.Count)
    $compileErr | Select-Object -First $MaxLines | ForEach-Object { Write-Host ('      {0}' -f $_) }
}

function Invoke-MassCompileDirectory {
    param(
        [string] $TargetDir,
        [string] $LogFile,
        [int]    $Port,
        [int]    $TimeoutMin
    )

    if (-not (Test-Path $TargetDir)) {
        throw "Directory does not exist: $TargetDir"
    }

    $viCount = @(Get-ChildItem $TargetDir -Recurse -File -Filter *.vi -ErrorAction SilentlyContinue).Count
    Write-Host ''
    Write-Host "=== MassCompile: $TargetDir ($viCount VIs)  ($(Get-Date -Format s)) ==="
    Write-Host "    log -> $LogFile"

    $logParent = Split-Path $LogFile -Parent
    if ($logParent -and -not (Test-Path $logParent)) {
        New-Item -ItemType Directory -Path $logParent -Force | Out-Null
    }

    $t0 = Get-Date

    # The CLI's first connect after LabVIEW launch often fails with -350000
    # even though VI Server is listening (see AGENTS.md), so retry on that
    # error only. Anything else, including a real compile, runs once.
    $maxAttempts = 4
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $job = Start-Job -ScriptBlock {
            param($Dir, $Log, $ViPort)
            & LabVIEWCLI -OperationName MassCompile -DirectoryToCompile $Dir `
                -LogFilePath $Log -PortNumber $ViPort 2>&1
            "EXITCODE=$LASTEXITCODE"
        } -ArgumentList $TargetDir, $LogFile, $Port

        $finished = Wait-Job $job -Timeout ($TimeoutMin * 60)
        $output = @()
        if ($finished) {
            $output = @(Receive-Job $job)
            $output | ForEach-Object { Write-Host ('   {0}' -f $_) }
        } else {
            Stop-Job $job
            Write-Warning "   MassCompile still running after $TimeoutMin min - stopped"
        }
        Remove-Job $job -Force -ErrorAction SilentlyContinue

        $connectFailed = $finished -and (($output | Out-String) -match '-350000')
        if (-not $connectFailed) { break }
        if ($attempt -lt $maxAttempts) {
            Write-Host "   CLI could not connect (-350000), retrying in 30 s (attempt $attempt of $maxAttempts)"
            Start-Sleep -Seconds 30
        } else {
            Write-Warning "   CLI never connected after $maxAttempts attempts"
        }
    }

    Write-Host ('   phase took {0:N1} min' -f ((Get-Date) - $t0).TotalMinutes)
    Show-MassCompileSummary -LogFile $LogFile
}

# --- resolve inputs ----------------------------------------------------------

$lv = Get-LabVIEWPaths
if (-not (Test-Path $lv.Exe)) {
    throw "LabVIEW not found at $($lv.Exe)"
}

$port = if ($Env:VI_SERVER_PORT) { [int] $Env:VI_SERVER_PORT } else { 3363 }
$timeout = if ($TimeoutMinutes -gt 0) { $TimeoutMinutes }
           elseif ($Env:COMPILE_MINUTES) { [int] $Env:COMPILE_MINUTES }
           else { 20 }
$startupMin = if ($Env:LABVIEW_STARTUP_MINUTES) { [int] $Env:LABVIEW_STARTUP_MINUTES } else { 20 }

$dirList = @()
if ($Directories) {
    $dirList = $Directories -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
} elseif ($Directory) {
    $dirList = @($Directory)
} elseif ($Env:COMPILE_DIRS) {
    $dirList = $Env:COMPILE_DIRS -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
} elseif ($Env:COMPILE_DIR) {
    $dirList = @($Env:COMPILE_DIR)
} else {
    $dirList = @(
        Join-Path $lv.ViLib 'SEF Energy\fs-choke-actuator'
    )
}

Write-Host '=== Mass Compile diagnostic ==='
Write-Host ('   LabVIEW {0}' -f $lv.Year)
Write-Host ('   targets: {0}' -f ($dirList -join '; '))
Write-Host ''
Write-Host '   WARNING: Mass Compile rewrites VIs in place. Never aim this at your'
Write-Host '            developer source tree or a bind-mounted host vi.lib.'

Invoke-LicenceSeed
$null = Wait-ViServer -LabVIEWExe $lv.Exe -Port $port -StartupMinutes $startupMin

$multi = $dirList.Count -gt 1
foreach ($i in 0..($dirList.Count - 1)) {
    $target = $dirList[$i]
    if ($LogPath -and -not $multi) {
        $log = $LogPath
    } elseif ($Env:COMPILE_LOG -and -not $multi) {
        $log = $Env:COMPILE_LOG
    } else {
        # Leaf directory name only (no full-path sanitizing).
        $leaf = Split-Path $target -Leaf
        if (-not $leaf) { $leaf = 'dir' }
        $log = if ($Env:COMPILE_LOG_DIR) {
            Join-Path $Env:COMPILE_LOG_DIR ("masscompile-{0}-{1}.log" -f $i, $leaf)
        } else {
            "C:\out\masscompile-$i-$leaf.log"
        }
    }

    Invoke-MassCompileDirectory -TargetDir $target -LogFile $log -Port $port -TimeoutMin $timeout
}

Write-Host ''
Write-Host '=== done ==='
