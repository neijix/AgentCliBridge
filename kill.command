#!/bin/bash
# AgentCliBridge — double-clickable macOS force-stop (Finder → Terminal).
# Delegates to kill.sh so there is one implementation of the pid check.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/kill.sh"
