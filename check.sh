#!/bin/bash
# The gate before a commit: restore, build with warnings as errors, every test (dotnet test).
# Twin: check.ps1. This computer's SDK and cache folders come from config.local/dotnet.env when
# that file exists (dotnet.env.example once the usage scaffold lands). --full = the same gate.
set -euo pipefail
cd "$(dirname "$0")"

for arg in "$@"; do
  case "$arg" in
    --full) ;;
    *) echo "usage: ./check.sh [--full]" >&2; exit 2 ;;
  esac
done

if [ -f config.local/dotnet.env ]; then
  set -a
  . config.local/dotnet.env
  set +a
fi
if [ -n "${DOTNET_ROOT:-}" ] && [ -x "$DOTNET_ROOT/dotnet" ]; then
  export PATH="$DOTNET_ROOT:$PATH"
fi
command -v dotnet >/dev/null 2>&1 || { echo "check: no .NET 10 SDK found (set DOTNET_ROOT in config.local/dotnet.env)" >&2; exit 1; }

echo "Running the gate."
dotnet test D3sk.AgentCli.slnx -c Release
