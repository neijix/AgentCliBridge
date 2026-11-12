# AgentCliBridge gateway — force stop (Windows twin of kill.sh).
# taskkill /F on the recorded pid only. Does not wait.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'start.ps1')
Stop-GatewayListenerForced
