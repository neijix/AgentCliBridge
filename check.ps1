# The gate before a commit: restore, build with warnings as errors, every test (dotnet test).
# Twin of check.sh; Windows PowerShell 5.1. config.local/dotnet.env (KEY=VALUE lines) is loaded
# when it exists. --full = the same gate.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
foreach ($arg in $args) {
  if ($arg -ne '--full') { Write-Error 'usage: ./check.ps1 [--full]'; exit 2 }
}
$envFile = Join-Path $PSScriptRoot 'config.local/dotnet.env'
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
      [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim("'").Trim('"'), 'Process')
    }
  }
}
if ($env:DOTNET_ROOT -and (Test-Path (Join-Path $env:DOTNET_ROOT 'dotnet.exe'))) {
  $env:PATH = $env:DOTNET_ROOT + [IO.Path]::PathSeparator + $env:PATH
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
  Write-Error 'check: no .NET 10 SDK found (set DOTNET_ROOT in config.local/dotnet.env)'; exit 1
}
Write-Host 'Running the gate.'
dotnet test D3sk.AgentCli.slnx -c Release
exit $LASTEXITCODE
