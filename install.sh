#!/usr/bin/env bash
# Install AgentCliBridge's gateway on this machine (macOS / Linux): Python 3.11+ and its venv,
# what start.sh sets up, without staying in the foreground. With --start, also starts the gateway
# in the background (log: gateway.log) unless something already answers on its port.
# Re-running is safe. Apps that list AgentCliBridge in their sibling-deps.txt (D3SKHAND) clone
# this repo beside themselves and run `install.sh --start` at every install, start and update.
# A packaged install runs it with AGENT_CLI_BRIDGE_INSTALL_DIR set (start.sh explains the layout):
# its setup built the venv, so this only checks it, and the log goes to <install>/logs.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:${PATH:-}"
# shellcheck source=start.sh
. ./start.sh  # functions only: its body runs when executed

load_gateway_env
PORT="${PORT:-4747}"
prepare_venv
echo "  OK AgentCliBridge gateway installed in ${AGENT_CLI_BRIDGE_INSTALL_DIR:-$PWD}"

if [ "${1:-}" = "--start" ]; then
  # Any HTTP answer means the port is taken: our gateway already runs, or a stranger keeps it.
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null; then
    echo "  OK AgentCliBridge gateway already answers on http://127.0.0.1:$PORT"
  else
    log="$(log_file)"
    nohup ./start.sh >>"$log" 2>&1 </dev/null &
    echo "  OK AgentCliBridge gateway starting on http://127.0.0.1:$PORT (log: $log)"
  fi
fi
