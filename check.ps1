# The gate before a commit: ruff, mypy, pytest, the node UI tests, code-health.
# This repo has no separate slow suite, so -Full runs the same commands.
# Twin of check.sh. uv and node are the paths Get-Command returned.
param([switch]$Full)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )
    & $File @ArgumentList
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# No separate slow suite: -Full selects this same gate.
if ($Full) { Write-Host 'Running the full gate.' } else { Write-Host 'Running the gate.' }

$uvx = Get-Command uvx -ErrorAction SilentlyContinue
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvx -or -not $uv) {
    Write-Host 'ERROR: uv is required (https://docs.astral.sh/uv/)'
    exit 1
}

# Same invocations CI used inline: uvx ruff, then uv run mypy and pytest.
Invoke-Tool -File $uvx.Source -ArgumentList @('ruff', 'check', 'agent_cli_bridge', 'tests')
foreach ($platform in @('linux', 'darwin', 'win32')) {
    Invoke-Tool -File $uv.Source -ArgumentList @(
        'run', '--isolated', '--with', 'mypy', '--with-editable', '.[dev]',
        'mypy', '--platform', $platform
    )
}
Invoke-Tool -File $uv.Source -ArgumentList @(
    'run', '--isolated', '--with-editable', '.[dev]', 'python', '-m', 'pytest', 'tests/', '-q'
)

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $ui = @(Get-ChildItem -Path 'tests/ui' -Filter '*.test.cjs' | ForEach-Object { $_.FullName })
    Invoke-Tool -File $node.Source -ArgumentList (@('--test') + $ui)
} else {
    Write-Host 'node: not installed, UI tests skipped'
}

$ch = Join-Path $HOME '.agents\skills\code-health\scripts\code_health.py'
if (Test-Path -LiteralPath $ch) {
    Invoke-Tool -File $uv.Source -ArgumentList @('run', '-q', $ch, 'check')
} else {
    Write-Host 'code-health: skill not installed, skipped'
}
