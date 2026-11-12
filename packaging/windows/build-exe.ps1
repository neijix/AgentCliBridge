# Build the Windows installer: dist\agentclibridge-<version>-windows-all-setup.exe (Inno Setup 6, agentclibridge.iss beside this file).
#
#   .\packaging\windows\build-exe.ps1 [-Archive <agentclibridge-<version>-any-all-snapshot.tar.gz>] [-Tag v1.0.0] [-Repo OWNER/REPO]
#                                     [-OutDir dist] [-Python <python>] [-Iscc <ISCC.exe>] [-StageOnly]
#
# The snapshot archive is the one `python -m bridge_installer.release snapshot` writes: given with
# -Archive, else built here (-Tag builds that tag, default HEAD). The script stages the setup folder
#   <OutDir>\exe-stage\agentclibridge-<version>-setup\{setup.ps1, setup.sh, app\ (the snapshot)}
# and, unless -StageOnly, compiles it with ISCC.exe (PATH, -Iscc, or "%ProgramFiles(x86)%\Inno Setup 6").
#
# Signing is optional: AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT (SHA-1 of a code-signing certificate in the user's
# or machine's store; no secret goes on a command line) turns it on, AGENTCLIBRIDGE_WIN_SIGN_TIMESTAMP
# overrides the timestamp server. Unset, the .exe is unsigned.
#
# Keep it Windows PowerShell 5.1 clean (the runner's default): no ternary, no &&, no ??.

param(
    [string]$Archive = '',
    [string]$Tag = '',
    [string]$Repo = '',
    [string]$OutDir = '',
    [string]$Python = '',
    [string]$Iscc = '',
    [switch]$StageOnly
)

$ErrorActionPreference = 'Stop'

function Stop-Build {
    param([string]$Message)
    [Console]::Error.WriteLine("ERROR: $Message")
    exit 1
}

$here = $PSScriptRoot
$repo = [IO.Path]::GetFullPath((Join-Path $here '../..'))
$onWindows = ($env:OS -eq 'Windows_NT')
$manifestName = 'agentclibridge-snapshot.json'    # bridge_installer MANIFEST_NAME
$timestampDefault = 'http://timestamp.digicert.com'

if ($OutDir -eq '') { $OutDir = Join-Path $repo 'dist' }
if (-not [IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path (Get-Location).ProviderPath $OutDir }
$OutDir = [IO.Path]::GetFullPath($OutDir)

# --- the snapshot archive ----------------------------------------------------------------------
if ($Archive -eq '') {
    if ($Python -eq '') {
        foreach ($name in 'python3.12', 'python3', 'python') {
            $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $Python = $found.Source; break }
        }
    }
    if ($Python -eq '') { Stop-Build 'Python 3 is needed to build the snapshot archive: pass -Python, or -Archive' }
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $releaseArgs = @('-m', 'bridge_installer.release', 'snapshot', '--out', $OutDir)
    if ($Tag -ne '') { $releaseArgs += @('--tag', $Tag) }
    if ($Repo -ne '') { $releaseArgs += @('--repo', $Repo) }
    $env:PYTHONPATH = $repo
    $env:PYTHONDONTWRITEBYTECODE = '1'
    Push-Location -LiteralPath $repo
    try {
        $ErrorActionPreference = 'Continue'
        $lines = & $Python @releaseArgs
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    } finally {
        Pop-Location
    }
    if ($code -ne 0) { Stop-Build "the snapshot archive was not built (exit $code)" }
    $Archive = [string](@($lines)[-1])
}
if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { Stop-Build "$Archive is not a file" }
$Archive = [IO.Path]::GetFullPath($Archive)

# agentclibridge-<version>-any-all-snapshot.tar.gz (bridge_installer/release.py snapshot_name)
$match = [regex]::Match([IO.Path]::GetFileName($Archive), '^agentclibridge-(?<v>[0-9][0-9A-Za-z.+-]*)-any-all-snapshot\.tar\.gz$')
if (-not $match.Success) { Stop-Build "$Archive is not named agentclibridge-<version>-any-all-snapshot.tar.gz" }
$version = $match.Groups['v'].Value

# --- stage the setup folder --------------------------------------------------------------------
$tar = 'tar'
if ($onWindows) {
    # Windows' own bsdtar: a GNU tar on PATH (Git for Windows) reads "C:\..." as a remote host.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $tar -PathType Leaf)) { Stop-Build 'tar.exe is missing (Windows 10 1803 or later has it)' }
}

# Refuse an archive that would write outside its folder before anything is extracted.
$ErrorActionPreference = 'Continue'
$names = & $tar -tzf $Archive
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { Stop-Build "$Archive cannot be read as a tar.gz (exit $code)" }
foreach ($entry in $names) {
    $text = [string]$entry
    if ($text.StartsWith('/') -or $text.StartsWith('\') -or $text -match '^[A-Za-z]:' -or $text -match '(^|[/\\])\.\.([/\\]|$)') {
        Stop-Build "$Archive holds an entry outside its folder: $text"
    }
}

$stageRoot = Join-Path $OutDir 'exe-stage'
$setupName = "agentclibridge-$version-setup"
$stage = Join-Path $stageRoot $setupName
if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
$appDir = Join-Path $stage 'app'
New-Item -ItemType Directory -Force -Path $appDir | Out-Null

$ErrorActionPreference = 'Continue'
& $tar -xzf $Archive -C $appDir
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { Stop-Build "extracting $Archive failed (exit $code)" }

$manifestPath = Join-Path $appDir $manifestName
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Stop-Build "$Archive holds no ${manifestName}: it is not a snapshot" }
if (-not (Test-Path -LiteralPath (Join-Path $appDir 'bridge_installer/__main__.py') -PathType Leaf)) {
    Stop-Build "$Archive holds no bridge_installer: it has no setup wizard"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.version -ne $version) { Stop-Build "$Archive is named for $version but its manifest says $($manifest.version)" }

Copy-Item -LiteralPath (Join-Path $repo 'packaging/setup.ps1') -Destination (Join-Path $stage 'setup.ps1')
$setupSh = Join-Path $repo 'packaging/setup.sh'
if (Test-Path -LiteralPath $setupSh -PathType Leaf) { Copy-Item -LiteralPath $setupSh -Destination (Join-Path $stage 'setup.sh') }

Write-Host "Staged $stage"
if ($StageOnly) { exit 0 }

# --- compile -----------------------------------------------------------------------------------
if (-not $onWindows) { Stop-Build 'Inno Setup runs on Windows only (use -StageOnly to check the staged folder here)' }
if ($Iscc -eq '') {
    $found = Get-Command 'ISCC.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $Iscc = $found.Source }
}
if ($Iscc -eq '') {
    foreach ($base in ${env:ProgramFiles(x86)}, $env:ProgramFiles) {
        if ($base) {
            $candidate = Join-Path $base 'Inno Setup 6\ISCC.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $Iscc = $candidate; break }
        }
    }
}
if ($Iscc -eq '' -or -not (Test-Path -LiteralPath $Iscc -PathType Leaf)) {
    Stop-Build 'ISCC.exe (Inno Setup 6) was not found: put it on PATH or pass -Iscc'
}

$isccArgs = @("/DVersion=$version", "/DStageDir=$stage", "/DOutDir=$OutDir")
$thumbprint = $env:AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT
if ($thumbprint) {
    if ($thumbprint -notmatch '^[0-9A-Fa-f]{40}$') { Stop-Build 'AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT is not a 40-digit SHA-1 thumbprint' }
    $signtool = Get-Command 'signtool.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $signPath = ''
    if ($signtool) {
        $signPath = $signtool.Source
    } else {
        $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        if (Test-Path -LiteralPath $kits) {
            $latest = Get-ChildItem -LiteralPath $kits -Recurse -Filter 'signtool.exe' -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName | Select-Object -Last 1
            if ($latest) { $signPath = $latest.FullName }
        }
    }
    if ($signPath -eq '') { Stop-Build 'signing was asked for but signtool.exe was not found (Windows SDK)' }
    $stamp = $env:AGENTCLIBRIDGE_WIN_SIGN_TIMESTAMP
    if (-not $stamp) { $stamp = $timestampDefault }
    # $q is Inno's quote, $f the file to sign; the certificate is named by thumbprint, never a password.
    $signCommand = '$q' + $signPath + '$q sign /sha1 ' + $thumbprint + ' /fd sha256 /tr ' + $stamp + ' /td sha256 $f'
    $isccArgs += @('/Sagentclibridge=' + $signCommand, '/DSignToolName=agentclibridge')
}
$isccArgs += (Join-Path $here 'agentclibridge.iss')

$ErrorActionPreference = 'Continue'
& $Iscc @isccArgs
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { Stop-Build "ISCC.exe failed (exit $code)" }

$exe = Join-Path $OutDir "agentclibridge-$version-windows-all-setup.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Stop-Build "ISCC.exe did not write $exe" }
Remove-Item -LiteralPath $stageRoot -Recurse -Force
Write-Host $exe
