#!/bin/bash
# AgentCliBridge — double-clickable macOS stop (Finder → Terminal).
# Delegates to stop.sh so there is one implementation of the pid check.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/stop.sh"
