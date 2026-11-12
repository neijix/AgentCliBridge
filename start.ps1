# AgentCliBridge gateway — one-command start (Windows twin of start.sh).
#
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# OpenAI-compatible endpoint over the local AI coding CLIs at
# http://127.0.0.1:4747/v1. Records the listener it starts in .gateway.pid.
# A different program already bound to the port is left alone. stop.ps1 / kill.ps1
# signal only that recorded pid, and only while it is still this gateway.
# Safe to re-run; setup steps are idempotent.
#
# stop.ps1, kill.ps1 and install.ps1 dot-source this file. Start-Gateway runs only when this
# file itself is executed.
#
# A packaged install (packaging/setup.ps1) runs this file from <install>\app with
# AGENT_CLI_BRIDGE_INSTALL_DIR=<install>: the venv, the pid file, the env file and the log then
# live in that folder (venv\, state\gateway.pid, gateway.env, logs\gateway.log), the env file
# overrides the environment, and no Python is searched for: the setup built the venv.
$ErrorActionPreference = 'Stop'
$script:GatewayRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $script:GatewayRoot) { throw 'start.ps1 could not locate its own directory' }
$script:InstallDir = [string]$env:AGENT_CLI_BRIDGE_INSTALL_DIR

function Get-VenvDir {
    if ($script:InstallDir) { return (Join-Path $script:InstallDir 'venv') }
    return (Join-Path $script:GatewayRoot 'venv')
}

function Get-EnvFile {
    if ($script:InstallDir) { return (Join-Path $script:InstallDir 'gateway.env') }
    return (Join-Path $script:GatewayRoot '.env')
}

# The folder of gateway.log and gateway.err.log.
function Get-LogDir {
    if (-not $script:InstallDir) { return $script:GatewayRoot }
    $dir = Join-Path $script:InstallDir 'logs'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

function Format-NativeArguments {
    param([string[]]$ArgumentList)
    # .NET Framework (Windows PowerShell 5.1) takes one argument string.
    $parts = @()
    foreach ($arg in $ArgumentList) {
        $text = [string]$arg
        if ($text -match '[\s"]') {
            $parts += '"' + ($text -replace '"', '\"') + '"'
        } else {
            $parts += $text
        }
    }
    $parts -join ' '
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )
    # Windows PowerShell 5.1 promotes a native exe's stderr to a terminating
    # NativeCommandError while ErrorActionPreference is Stop. winget, python
    # and pip write to stderr on the first-run path. Starting the process here
    # leaves that stderr on the console instead of the PowerShell error stream.
    $ErrorActionPreference = 'Continue'
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $PSNativeCommandUseErrorActionPreference = $false
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = (Format-NativeArguments $ArgumentList)
    $start.UseShellExecute = $false
    $start.WorkingDirectory = (Get-Location).Path
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    [void]$process.Start()
    $process.WaitForExit()
    $global:LASTEXITCODE = $process.ExitCode
}

function Test-PythonAtLeast311 {
    param([Parameter(Mandatory = $true)][string]$PythonPath)
    if (-not (Test-Path -LiteralPath $PythonPath)) { return $false }
    Invoke-Native -FilePath $PythonPath -ArgumentList @(
        '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
    )
    return ($LASTEXITCODE -eq 0)
}

function Find-Python311 {
    $seen = @{}
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($name in @('python3.13', 'python3.12', 'python3.11', 'python3', 'python')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $candidates.Add([string]$cmd.Source) }
    }
    $roots = @()
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA 'Programs\Python') }
    if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles 'Python') }
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $found = @(Get-ChildItem -LiteralPath $root -Filter python.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue)
        foreach ($item in $found) { $candidates.Add($item.FullName) }
    }
    foreach ($path in $candidates) {
        if (-not $path -or $seen.ContainsKey($path)) { continue }
        $seen[$path] = $true
        if (-not [System.IO.Path]::IsPathRooted($path)) { continue }
        if (Test-PythonAtLeast311 $path) { return $path }
    }
    return $null
}

function Get-WingetExe {
    $cmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    if ($env:LOCALAPPDATA) {
        $fallback = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\winget.exe'
        if (Test-Path -LiteralPath $fallback) { return $fallback }
    }
    return $null
}

function Get-TaskkillExe {
    $windows = $env:SystemRoot
    if (-not $windows) { $windows = 'C:\Windows' }
    $path = Join-Path $windows 'System32\taskkill.exe'
    if (Test-Path -LiteralPath $path) { return $path }
    return $null
}

function Ensure-Venv {
    param([Parameter(Mandatory = $true)][string]$Python)
    $venvDir = Get-VenvDir
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'
    if ((Test-Path -LiteralPath $venvPy) -and -not (Test-PythonAtLeast311 $venvPy)) {
        Write-Host 'Existing venv uses a Python older than 3.11 — rebuilding.'
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Write-Host 'Creating venv...'
        Invoke-Native -FilePath $Python -ArgumentList @('-m', 'venv', $venvDir)
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed ($LASTEXITCODE)" }
    }
    Invoke-Native -FilePath $venvPy -ArgumentList @('-c', 'import fastapi, uvicorn, httpx')
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing gateway dependencies...'
        Invoke-Native -FilePath $venvPy -ArgumentList @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed ($LASTEXITCODE)" }
        Invoke-Native -FilePath $venvPy -ArgumentList @('-m', 'pip', 'install', '--quiet', '-e', '.[server]')
        if ($LASTEXITCODE -ne 0) { throw "gateway install failed ($LASTEXITCODE)" }
    }
    return $venvPy
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path, [switch]$Override)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        $line = $raw.TrimEnd("`r")
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $eq = $trimmed.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $trimmed.Substring(0, $eq).Trim()
        if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $value = $trimmed.Substring($eq + 1)
        $value = [regex]::Replace($value, '\s+#.*$', '')
        $value = $value.Trim()
        if ($Override -or -not (Test-Path -LiteralPath "Env:$key")) {
            Set-Item -LiteralPath "Env:$key" -Value $value
        }
    }
}

# The env file of this layout: a packaged install's gateway.env wins over the environment.
function Import-GatewayEnv {
    if ($script:InstallDir) { Import-DotEnv -Path (Get-EnvFile) -Override } else { Import-DotEnv -Path (Get-EnvFile) }
}

function Get-PidFile {
    if (-not $script:InstallDir) { return (Join-Path $script:GatewayRoot '.gateway.pid') }
    $dir = Join-Path $script:InstallDir 'state'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return (Join-Path $dir 'gateway.pid')
}

function Read-RecordedPid {
    $file = Get-PidFile
    if (-not (Test-Path -LiteralPath $file)) { return 0 }
    $text = [System.IO.File]::ReadAllText($file)
    if ($text -match '^\s*(\d+)\s*$') { return [int]$Matches[1] }
    return 0
}

function Write-RecordedPid {
    param([Parameter(Mandatory = $true)][int]$GatewayId)
    [System.IO.File]::WriteAllText((Get-PidFile), "$GatewayId")
}

function Clear-RecordedPid {
    $file = Get-PidFile
    if (Test-Path -LiteralPath $file) {
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
    }
}

function Get-PortListeners {
    param([Parameter(Mandatory = $true)][int]$ListenPort)
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        throw 'Get-NetTCPConnection is required to see who holds the port'
    }
    $ErrorActionPreference = 'Continue'
    $rows = @(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($row in $rows) { $row.OwningProcess }
}

# Our listener is the venv interpreter for this checkout, running the gateway module.
# A recycled pid whose command line is something else is not signaled.
function Test-GatewayProcess {
    param([Parameter(Mandatory = $true)][int]$GatewayId)
    if ($GatewayId -le 0) { return $false }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $GatewayId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    $cmd = [string]$proc.CommandLine
    if ($cmd -notlike '*agent_cli_bridge.gateway*') { return $false }
    $exe = [string]$proc.ExecutablePath
    if (-not $exe) { return $false }
    $venvPy = Join-Path (Get-VenvDir) 'Scripts\python.exe'
    if ($exe -eq $venvPy) { return $true }
    if ($script:InstallDir -and $exe.StartsWith($script:InstallDir, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    return $exe.StartsWith($script:GatewayRoot, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-GatewayPort {
    param([Parameter(Mandatory = $true)][int]$ListenPort)
    $holders = @(Get-PortListeners -ListenPort $ListenPort)
    if ($holders.Count -eq 0) { return }
    $holder = [int]$holders[0]
    if (-not (Test-GatewayProcess $holder)) {
        Write-Host "Port $ListenPort is used by another program and was left alone."
        exit 1
    }
    $taskkill = Get-TaskkillExe
    if (-not $taskkill) { throw 'taskkill.exe was not found' }
    Write-Host "Replacing the gateway already listening on port $ListenPort..."
    Invoke-Native -FilePath $taskkill -ArgumentList @('/PID', "$holder")
    $deadline = (Get-Date).AddSeconds(2)
    do {
        $left = @(Get-PortListeners -ListenPort $ListenPort)
        if ($left.Count -eq 0) { return }
        if (-not (Test-GatewayProcess ([int]$left[0]))) { break }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    $left = @(Get-PortListeners -ListenPort $ListenPort)
    if ($left.Count -gt 0 -and (Test-GatewayProcess ([int]$left[0]))) {
        Invoke-Native -FilePath $taskkill -ArgumentList @('/PID', "$($left[0])", '/F')
        Start-Sleep -Milliseconds 200
    }
    $left = @(Get-PortListeners -ListenPort $ListenPort)
    if ($left.Count -gt 0) {
        Write-Host "Port $ListenPort is used by another program and was left alone."
        exit 1
    }
}

function Stop-GatewayListener {
    $gatewayId = Read-RecordedPid
    if ($gatewayId -le 0 -or -not (Test-GatewayProcess $gatewayId)) {
        Clear-RecordedPid
        Write-Host 'AgentCliBridge gateway is not running.'
        exit 0
    }
    $taskkill = Get-TaskkillExe
    if (-not $taskkill) { throw 'taskkill.exe was not found' }
    Invoke-Native -FilePath $taskkill -ArgumentList @('/PID', "$gatewayId")
    $deadline = (Get-Date).AddSeconds(5)
    do {
        if (-not (Test-GatewayProcess $gatewayId)) {
            Clear-RecordedPid
            Write-Host 'Stopped.'
            exit 0
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    if (-not (Test-GatewayProcess $gatewayId)) {
        Clear-RecordedPid
        Write-Host 'Stopped.'
        exit 0
    }
    Write-Host "AgentCliBridge gateway (pid $gatewayId) is still running."
    exit 1
}

function Stop-GatewayListenerForced {
    $gatewayId = Read-RecordedPid
    if ($gatewayId -le 0 -or -not (Test-GatewayProcess $gatewayId)) {
        Clear-RecordedPid
        Write-Host 'AgentCliBridge gateway is not running.'
        exit 0
    }
    $taskkill = Get-TaskkillExe
    if (-not $taskkill) { throw 'taskkill.exe was not found' }
    Invoke-Native -FilePath $taskkill -ArgumentList @('/PID', "$gatewayId", '/F')
    Clear-RecordedPid
    Write-Host 'Killed.'
    exit 0
}

# Python 3.11+ (winget installs it when missing), then the gateway's venv. install.ps1 shares it.
function Initialize-GatewayVenv {
    if ($script:InstallDir) {
        $venvPy = Join-Path (Get-VenvDir) 'Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPy) {
            Invoke-Native -FilePath $venvPy -ArgumentList @('-c', 'import fastapi, uvicorn, httpx')
            if ($LASTEXITCODE -eq 0) { return $venvPy }
        }
        throw "$(Get-VenvDir) is missing or broken: run the AgentCliBridge setup again"
    }
    $python = Find-Python311
    if (-not $python) {
        $winget = Get-WingetExe
        if ($winget) {
            Write-Host 'Python 3.11+ not found — installing via winget...'
            Invoke-Native -FilePath $winget -ArgumentList @(
                'install', '-e', '--id', 'Python.Python.3.11',
                '--accept-package-agreements', '--accept-source-agreements'
            )
            $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $user = [Environment]::GetEnvironmentVariable('Path', 'User')
            $env:Path = "$machine;$user"
            $python = Find-Python311
        }
    }
    if (-not $python) {
        throw 'Python 3.11+ is required (winget install -e --id Python.Python.3.11)'
    }
    return (Ensure-Venv -Python $python)
}

function Start-Gateway {
    Set-Location -LiteralPath $script:GatewayRoot
    Import-GatewayEnv
    if (-not $env:PORT) { $env:PORT = '4747' }
    $listenPort = [int]$env:PORT
    Assert-GatewayPort -ListenPort $listenPort
    $venvPy = Initialize-GatewayVenv
    Write-Host "AgentCliBridge gateway -> http://127.0.0.1:$listenPort/v1  (Ctrl+C to stop)"
    $gateway = Start-Process -FilePath $venvPy -ArgumentList @('-m', 'agent_cli_bridge.gateway') `
        -WorkingDirectory $script:GatewayRoot -PassThru -NoNewWindow
    Write-RecordedPid -GatewayId $gateway.Id
    try {
        Wait-Process -Id $gateway.Id
    } finally {
        if ($gateway.HasExited) {
            $recorded = Read-RecordedPid
            if ($recorded -eq $gateway.Id) { Clear-RecordedPid }
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Start-Gateway
}
