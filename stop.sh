#!/bin/bash
# AgentCliBridge gateway — graceful stop. SIGTERM to the recorded listener only,
# and only while that pid is still this gateway. Waits up to 5 seconds.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"
# shellcheck source=start.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/start.sh"
stop_recorded_gateway
