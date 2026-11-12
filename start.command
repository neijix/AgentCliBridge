#!/bin/bash
# AgentCliBridge — double-clickable macOS launcher (Finder → Terminal).
#
# Thin wrapper over start.sh so there is a single source of truth for the
# actual startup logic (dependency checks, venv, kill-before-start, exec).
# Double-clicking a .command opens Terminal with a login-ish shell whose PATH
# often lacks Homebrew; start.sh prepends it, so delegating here is enough.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/start.sh"
