# Install AgentCliBridge's gateway on this machine (Windows twin of install.sh): Python 3.11+ and
# its venv, what start.ps1 sets up, without staying in the foreground. With -Start, also starts
# the gateway in the background, no window (log: gateway.log, gateway.err.log) unless something
# already answers on its port.
# Re-running is safe. Apps that list AgentCliBridge in their sibling-deps.txt (D3SKHAND) clone
# this repo beside themselves and run `install.ps1 -Start` at every install, start and update.
# A packaged install runs it with AGENT_CLI_BRIDGE_INSTALL_DIR set (start.ps1 explains the layout):
# its setup built the venv, so this only checks it, and the logs go to <install>\logs.
param([switch]$Start)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'start.ps1')  # functions only: Start-Gateway runs when executed

Import-GatewayEnv
if (-not $env:PORT) { $env:PORT = '4747' }
$listenPort = [int]$env:PORT
$null = Initialize-GatewayVenv
$installedIn = $PSScriptRoot
if ($script:InstallDir) { $installedIn = $script:InstallDir }
Write-Host "  OK AgentCliBridge gateway installed in $installedIn"

# Any HTTP answer means the port is taken: our gateway already runs, or a stranger keeps it.
function Test-PortAnswers([int]$Port) {
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
        return $true
    } catch {
        return ($null -ne $_.Exception.Response)
    }
}

if ($Start) {
    if (Test-PortAnswers $listenPort) {
        Write-Host "  OK AgentCliBridge gateway already answers on http://127.0.0.1:$listenPort"
    } else {
        $shell = (Get-Process -Id $PID).Path
        $logDir = Get-LogDir
        Start-Process -FilePath $shell -WindowStyle Hidden -WorkingDirectory $PSScriptRoot `
            -RedirectStandardOutput (Join-Path $logDir 'gateway.log') `
            -RedirectStandardError (Join-Path $logDir 'gateway.err.log') `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'start.ps1'))
        Write-Host "  OK AgentCliBridge gateway starting on http://127.0.0.1:$listenPort (log: $(Join-Path $logDir 'gateway.log'))"
    }
}
exit 0
