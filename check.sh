#!/bin/bash
# The gate before a commit: ruff, mypy, pytest, the node UI tests, code-health.
# This repo has no separate slow suite, so --full runs the same commands.
# Twin: check.ps1. uv and node are the paths command -v returned.
set -euo pipefail
cd "$(dirname "$0")"

full=0
for arg in "$@"; do
  case "$arg" in
    --full) full=1 ;;
    *) echo "usage: ./check.sh [--full]" >&2; exit 2 ;;
  esac
done
# No separate slow suite: --full selects this same gate.
if [ "$full" -eq 1 ]; then
  echo "Running the full gate."
else
  echo "Running the gate."
fi

uvx_bin="$(command -v uvx 2>/dev/null || true)"
uv_bin="$(command -v uv 2>/dev/null || true)"
if [ -z "$uvx_bin" ] || [ -z "$uv_bin" ]; then
  echo "ERROR: uv is required (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

# Same invocations CI used inline: uvx ruff, then uv run mypy and pytest.
"$uvx_bin" ruff check agent_cli_bridge tests
for platform in linux darwin win32; do
  "$uv_bin" run --isolated --with mypy --with-editable ".[dev]" mypy --platform "$platform"
done
"$uv_bin" run --isolated --with-editable ".[dev]" python -m pytest tests/ -q

node_bin="$(command -v node 2>/dev/null || true)"
if [ -n "$node_bin" ]; then
  ui_tests=(tests/ui/*.test.cjs)
  "$node_bin" --test "${ui_tests[@]}"
else
  echo "node: not installed, UI tests skipped"
fi

CH="$HOME/.agents/skills/code-health/scripts/code_health.py"
if [ -f "$CH" ]; then
  "$uv_bin" run -q "$CH" check
else
  echo "code-health: skill not installed, skipped"
fi
