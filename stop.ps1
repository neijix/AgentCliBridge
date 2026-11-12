# AgentCliBridge gateway — graceful stop (Windows twin of stop.sh).
# taskkill without /F, then wait 5 seconds. Exit 1 if that pid is still the gateway.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'start.ps1')
Stop-GatewayListener
