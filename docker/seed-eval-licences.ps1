<#
.SYNOPSIS
    Put TPLAT-licensed add-ons into their 30-day evaluation in a worker image.

.DESCRIPTION
    Third-party toolkits licensed with NI's Third Party Licensing & Activation
    Toolkit (TPLAT) ship an unactivated .lf beside the .lvlib under vi.lib.
    A real VIPM install copies that file to:

      C:\ProgramData\National Instruments\Partners\<Vendor>\Licenses\

    Without it, LabVIEW logs "Error opening license file", pp_eztrial1() returns
    status 0, and every VI in the library is broken — even though NI's Standard
    Mode documentation says a registered add-on "will start off in evaluation
    mode" with the run arrow unbroken.

    Do NOT copy a developer machine's activated Partners tree into a container.
    Those .lf files are bound to the activating machine's TPLAT computer number,
    fail to open elsewhere, and do not fall back to evaluation.

    Run this after VIPM has installed packages into vi.lib, or after any step
    that copies a host vi.lib tree into the image. It is safe to run repeatedly:
    existing licence files are left untouched.

.NOTES
    Environment overrides:
      LABVIEW_VERSION   LabVIEW year directory under Program Files. Default 2026.
#>

$ErrorActionPreference = 'Stop'

$year = if ($Env:LABVIEW_VERSION) { $Env:LABVIEW_VERSION } else { '2026' }
$lvDir = "C:\Program Files\National Instruments\LabVIEW $year"
$viLib = Join-Path $lvDir 'vi.lib'
$partners = 'C:\ProgramData\National Instruments\Partners'

if (-not (Test-Path $viLib)) {
    throw "LabVIEW vi.lib not found at $viLib"
}

$lfs = @(Get-ChildItem $viLib -Recurse -Filter '*.lf' -File -ErrorAction SilentlyContinue)
Write-Host "=== TPLAT licence seeding ($($lfs.Count) as-shipped .lf under vi.lib) ==="

if ($lfs.Count -eq 0) {
    Write-Host '   nothing to seed — vi.lib contains no .lf files yet'
    exit 0
}

$seeded = 0
$skipped = 0
foreach ($lf in $lfs) {
    $rel = $lf.FullName.Replace($viLib + '\', '')
    $parts = $rel -split '\\'
    $vendor = if ($parts[0] -eq 'addons') { $parts[1] } else { $parts[0] }

    $destDir = Join-Path $partners (Join-Path $vendor 'Licenses')
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    $target = Join-Path $destDir $lf.Name
    if (Test-Path $target) {
        Write-Host ('   {0,-22} {1,-46} already present' -f $vendor, $lf.Name)
        $skipped++
    } else {
        Copy-Item $lf.FullName $target -Force
        Write-Host ('   {0,-22} {1,-46} seeded' -f $vendor, $lf.Name)
        $seeded++
    }
}

Write-Host ''
Write-Host "=== done: $seeded seeded, $skipped already present ==="
Get-ChildItem $partners -Recurse -File -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ('   {0}' -f $_.FullName.Replace($partners + '\', '')) }
