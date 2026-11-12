#!/bin/bash
# AgentCliBridge gateway — force stop. SIGKILL to the recorded listener only,
# and only while that pid is still this gateway. Does not wait.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"
# shellcheck source=start.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/start.sh"
kill_recorded_gateway
