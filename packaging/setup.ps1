# AgentCliBridge setup, step one (Windows). Sits beside the snapshot in the setup folder:
#   <setup folder>\setup.sh  setup.ps1  app\ (the snapshot)
# It asks the install folder first, finds uv or fetches it, makes sure Python 3.12 is there, then
# hands every argument to the setup wizard (python -m bridge_installer, run from <setup>\app).
# The twin is setup.sh (macOS / Linux): the two behave the same, keep them in step.
#
# uv, Python 3.12 and temporary files go in the install folder (--dir, else
# AGENTCLIBRIDGE_SETUP_DIR, else one prompt with no default): <folder>\uv and <folder>\temp, never
# the user profile. A folder that is non-empty and is not an AgentCliBridge install is refused
# before anything is written.
#
# Every argument is passed on as it came (no param block), except that a --dir value becomes absolute.

$ErrorActionPreference = 'Stop'

$ManifestName = 'agentclibridge-snapshot.json'          # bridge_installer MANIFEST_NAME
$PythonVersion = '3.12'                                 # bridge_installer PYTHON_VERSION
$UvInstallPs1 = 'https://astral.sh/uv/install.ps1'

function Stop-Setup {
    param([string]$Message)
    [Console]::Error.WriteLine("ERROR: $Message")
    exit 1
}

$onWindows = ($PSVersionTable.PSVersion.Major -lt 6) -or $IsWindows
$exe = if ($onWindows) { '.exe' } else { '' }
$startDir = (Get-Location).ProviderPath
$here = $PSScriptRoot
$app = Join-Path $here 'app'

if (-not (Test-Path -LiteralPath (Join-Path $app 'bridge_installer/__main__.py') -PathType Leaf)) {
    Stop-Setup "$app holds no AgentCliBridge snapshot: run setup.ps1 from the setup folder it came in"
}

# An absolute path: the wizard runs in the snapshot folder, so a relative one is taken from where
# the user ran this script.
function Get-AbsolutePath {
    param([string]$Path)
    if ($Path -eq '~') { return $HOME }
    if ($Path.StartsWith('~/') -or $Path.StartsWith('~\')) { return (Join-Path $HOME $Path.Substring(2)) }
    if ([IO.Path]::IsPathRooted($Path)) { return $Path }
    return (Join-Path $startDir $Path)
}

$wizardArgs = New-Object System.Collections.Generic.List[string]
$dir = ''
$wantHelp = $false
$skipFolder = $false
$pending = $false
foreach ($arg in $args) {
    $arg = [string]$arg
    if ($pending) {
        if ($arg.StartsWith('-')) { Stop-Setup "--dir needs a folder, not $arg" }
        $arg = Get-AbsolutePath $arg
        $dir = $arg
        $pending = $false
    } elseif ($arg -eq '--dir') {
        $pending = $true
    } elseif ($arg.StartsWith('--dir=')) {
        $dir = Get-AbsolutePath $arg.Substring(6)
        $arg = '--dir=' + $dir
    } elseif ($arg -eq '-h' -or $arg -eq '--help') {
        $wantHelp = $true
    } elseif ($arg -eq '--uninstall' -or $arg -eq '--update') {
        $skipFolder = $true
    }
    $wizardArgs.Add($arg)
}
if ($pending) { Stop-Setup '--dir needs a folder' }

# The wizard gets no uv or temp set (the gateway it starts must not inherit them), only the
# snapshot on its path and the uv to build the venv with; it writes no bytecode into the snapshot.
function Start-Wizard {
    param([string]$Python, [string]$Uv = '')
    $env:PYTHONPATH = $app
    $env:PYTHONDONTWRITEBYTECODE = '1'
    if ($Uv) { $env:AGENT_CLI_BRIDGE_SETUP_UV = $Uv }
    Set-Location -LiteralPath $app
    $ErrorActionPreference = 'Continue'
    & $Python -m bridge_installer @wizardArgs
    exit $LASTEXITCODE
}

# The wizard's help needs no toolchain and no folder: nothing is fetched or written.
if ($wantHelp) {
    $found = $null
    foreach ($name in 'python3.12', 'python3', 'python') {
        $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { break }
    }
    if (-not $found) { Stop-Setup 'Python 3 is needed to show the help' }
    Start-Wizard $found.Source
}

# The folder first: it is refused here, before anything is written, and uv and Python go into it.
if (-not $dir) {
    if ($env:AGENTCLIBRIDGE_SETUP_DIR) {
        $dir = Get-AbsolutePath $env:AGENTCLIBRIDGE_SETUP_DIR
    } elseif (-not [Console]::IsInputRedirected) {
        $answer = Read-Host 'Install folder (no default)'
        if (-not $answer) { Stop-Setup 'no install folder given (--dir <folder> or AGENTCLIBRIDGE_SETUP_DIR)' }
        $dir = Get-AbsolutePath $answer
    } else {
        Stop-Setup 'the install folder is required: --dir <folder> or AGENTCLIBRIDGE_SETUP_DIR'
    }
    $wizardArgs.Add('--dir')
    $wizardArgs.Add($dir)
}
if ((Test-Path -LiteralPath $dir) -and -not (Test-Path -LiteralPath $dir -PathType Container)) {
    Stop-Setup "$dir exists and is not a folder"
}
$sep = [IO.Path]::DirectorySeparatorChar
if (($dir.TrimEnd('\', '/') + $sep).StartsWith($here.TrimEnd('\', '/') + $sep, [StringComparison]::OrdinalIgnoreCase)) {
    Stop-Setup "$dir is inside the setup folder ($here): choose another folder"
}
if (-not $skipFolder -and (Test-Path -LiteralPath $dir -PathType Container) -and
    -not (Test-Path -LiteralPath (Join-Path $dir "app/$ManifestName") -PathType Leaf)) {
    # Only this script's own uv\ and temp\ (a run that stopped before the wizard) leave it new, as
    # bridge_installer/apply.py SETUP_BOOTSTRAP says.
    foreach ($entry in @(Get-ChildItem -LiteralPath $dir -Force)) {
        $isOurs = ($entry.Name -eq 'uv' -or $entry.Name -eq 'temp') -and $entry.PSIsContainer -and
            -not ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)
        if (-not $isOurs) {
            Stop-Setup "$dir is not empty and is not an AgentCliBridge install (no app\$ManifestName): choose an empty or new folder"
        }
    }
}

$root = $dir
$bin = Join-Path $root 'uv/bin'
$tempDir = Join-Path $root 'temp'

function Set-ProcessVariable {
    param([string]$Name, $Value)   # untyped: a typed $null would become an empty string
    if ($null -eq $Value) {
        Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
    } else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    }
}

# Run a command with uv and the temp pinned at $root (bridge_installer/apply.py uv_env), Python
# only from uv's own folder. Returns the output lines; the exit code is in $script:LastExit.
function Invoke-Uv {
    param([scriptblock]$Command, [hashtable]$Extra = @{}, [switch]$Quiet)
    $vars = [ordered]@{
        UV_PYTHON = $null; UV_NO_MANAGED_PYTHON = $null; UV_PYTHON_DOWNLOADS = $null
        UV_SYSTEM_PYTHON = $null; UV_PROJECT = $null; VIRTUAL_ENV = $null
        TMP = $tempDir; TEMP = $tempDir; TMPDIR = $tempDir
        UV_CACHE_DIR = (Join-Path $root 'uv/cache')
        UV_PYTHON_INSTALL_DIR = (Join-Path $root 'uv/python')
        UV_PYTHON_BIN_DIR = $bin
        UV_TOOL_DIR = (Join-Path $root 'uv/tools')
        UV_TOOL_BIN_DIR = $bin
        UV_PYTHON_PREFERENCE = 'only-managed'
        PATH = $bin + [IO.Path]::PathSeparator + $env:PATH
    }
    foreach ($key in $Extra.Keys) { $vars[$key] = $Extra[$key] }
    $saved = @{}
    foreach ($key in $vars.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        Set-ProcessVariable $key $vars[$key]
    }
    try {
        # uv reports progress on stderr; under 'Stop' Windows PowerShell 5.1 would treat that as a
        # terminating error, so native calls run under 'Continue' and are judged by exit code.
        $ErrorActionPreference = 'Continue'
        if ($Quiet) { $out = & $Command 2>$null } else { $out = & $Command }
        $script:LastExit = $LASTEXITCODE
    } finally {
        foreach ($key in $vars.Keys) { Set-ProcessVariable $key $saved[$key] }
    }
    return $out
}

Write-Host "AgentCliBridge setup: uv and Python $PythonVersion are kept in $(Join-Path $root 'uv'), temporary files in $tempDir."
Write-Host '  (nothing is written to your user profile)'
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

$uv = $null
$candidates = @((Join-Path $bin "uv$exe"))
$onPath = Get-Command 'uv' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($onPath) { $candidates += $onPath.Source }
if ($onWindows) {
    # A fresh installer session has a stale PATH: look where uv usually lives too.
    $candidates += (Join-Path $HOME '.local/bin/uv.exe')
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA 'uv/uv.exe')
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs/uv/uv.exe')
    }
}
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $uv = $candidate; break }
}

if (-not $uv) {
    Write-Host "uv not found: fetching it from $UvInstallPs1 into $bin"
    # The script goes to a file first (a failed download runs nothing), then runs with
    # UV_UNMANAGED_INSTALL at $root: no install receipt in the user's config folder, no PATH edit.
    $scratch = Join-Path $tempDir ('uv-install.' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    try {
        $installer = Join-Path $scratch 'uv-install.ps1'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $UvInstallPs1 -OutFile $installer
        } catch {
            Stop-Setup "could not download ${UvInstallPs1}: $($_.Exception.Message)"
        }
        $shell = (Get-Process -Id $PID).Path
        Invoke-Uv -Extra @{ UV_UNMANAGED_INSTALL = $bin } -Command {
            & $shell -NoProfile -ExecutionPolicy Bypass -File $installer
        } | Out-Host
        if ($script:LastExit -ne 0) { Stop-Setup "uv's installer failed (exit code $script:LastExit)" }
    } finally {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $uv = Join-Path $bin "uv$exe"
    if (-not (Test-Path -LiteralPath $uv -PathType Leaf)) { Stop-Setup "uv's installer ran but $uv does not exist" }
} else {
    Write-Host "uv found: $uv (nothing to download)"
}

# --system skips any virtualenv in the current folder; Invoke-Uv limits uv to its managed Pythons.
Invoke-Uv -Quiet -Command { & $uv python find --system $PythonVersion } | Out-Null
if ($script:LastExit -ne 0) {
    Write-Host "Python $PythonVersion not found: installing it with uv into $(Join-Path $root 'uv/python')"
    Invoke-Uv -Command { & $uv python install $PythonVersion } | Out-Host
    if ($script:LastExit -ne 0) { Stop-Setup "uv could not install Python $PythonVersion" }
}
$python = Invoke-Uv -Command { & $uv python find --system $PythonVersion } | Select-Object -Last 1
if ($script:LastExit -ne 0 -or -not $python) { Stop-Setup "uv found no managed Python $PythonVersion" }

Start-Wizard ([string]$python) ([string]$uv)
