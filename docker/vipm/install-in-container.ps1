<#
.SYNOPSIS
    Entry point for the run-and-commit install. Copies the staged tooling to a
    container-local directory and applies it.

.DESCRIPTION
    Exists so the `docker run` command is a single -File invocation. Passing the
    equivalent inline needs nested quoting that the host shell expands first: a
    `$env:VIPC_DIR='...'` written inline is substituted by the calling PowerShell
    before Docker ever sees it, leaving a bare `='...'` in the container and the
    variable unset.

    Working in a copy matters when C:\vipm is bind-mounted from the host:
    extracting a bundled configuration writes hundreds of megabytes, which
    should not land in a source tree.
#>

$ErrorActionPreference = 'Stop'

$Source = if ($Env:VIPC_SOURCE_DIR) { $Env:VIPC_SOURCE_DIR } else { 'C:\vipm' }
$Work   = if ($Env:VIPC_DIR)        { $Env:VIPC_DIR }        else { 'C:\vipmwork' }

if (-not (Test-Path $Source)) { throw "Staged tooling not found at $Source." }

Write-Host "Copying staged VIPM tooling: $Source -> $Work"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
Copy-Item -Path (Join-Path $Source '*') -Destination $Work -Recurse -Force

$installer = Join-Path $Work 'install-vipc.ps1'
if (-not (Test-Path $installer)) { throw "install-vipc.ps1 was not found in $Work." }

$Env:VIPC_DIR = $Work
& $installer
exit $LASTEXITCODE
