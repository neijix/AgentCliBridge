#!/bin/bash
# AgentCliBridge gateway — one-command start (dashboard-discoverable via switchboard.json).
#
#   ./start.sh
#
# OpenAI-compatible endpoint over the local AI coding CLIs at
# http://127.0.0.1:4747/v1. Records the listener it starts in .gateway.pid.
# A different program already bound to the port is left alone. stop.sh / kill.sh
# signal only that recorded pid, and only while it is still this gateway.
# Safe to re-run; setup steps are idempotent.
#
# stop.sh and kill.sh source this file for the shared pid checks. The body runs
# only when the file itself is executed.
set -euo pipefail

# Finder / dashboard-launched shells often lack Homebrew on PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"

gateway_root() {
  (cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
}

pid_file() {
  printf '%s/.gateway.pid' "$(gateway_root)"
}

physical_dir() {
  local target="$1"
  target="${target#"${target%%[![:space:]]*}"}"
  target="${target%"${target##*[![:space:]]}"}"
  if [ -z "$target" ]; then
    return 0
  fi
  (cd "$target" 2>/dev/null && pwd -P) || true
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

# A '#' stays in the value unless whitespace comes first (URL=http://x/y#frag
# keeps the fragment; URL=http://x/y # note drops the note).
strip_inline_comment() {
  local value="$1"
  if [[ "$value" == *[[:space:]]#* ]]; then
    value="${value%%[[:space:]]#*}"
  fi
  trim "$value"
}

load_dotenv() {
  local file="$1" line trimmed key value
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    trimmed="$(trim "$line")"
    [ -z "$trimmed" ] && continue
    case "$trimmed" in
      \#*) continue ;;
    esac
    case "$trimmed" in
      *=*) ;;
      *) continue ;;
    esac
    key="$(trim "${trimmed%%=*}")"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="$(strip_inline_comment "${trimmed#*=}")"
    if [ -z "${!key+x}" ]; then
      export -- "$key=$value"
    fi
  done < "$file"
}

# A bare python3 on macOS is often the system 3.9. Probe versioned names and
# invoke the path command -v returned, never the bare name again.
is_supported_python() {
  "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1
}

find_python() {
  local candidate path
  for candidate in python3.13 python3.12 python3.11 python3; do
    path="$(command -v "$candidate" 2>/dev/null || true)"
    if [ -n "$path" ] && is_supported_python "$path"; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

ensure_venv() {
  local python="$1" venv_py="$2" root
  root="$(gateway_root)"
  if [ -x "$venv_py" ] && ! is_supported_python "$venv_py"; then
    echo "▶ Existing venv uses $("$venv_py" --version 2>&1) — rebuilding with $("$python" --version 2>&1)…"
    rm -rf "$root/venv"
  fi
  if [ ! -x "$venv_py" ]; then
    echo "▶ Creating venv ($("$python" --version 2>&1))…"
    "$python" -m venv "$root/venv"
  fi
  if ! "$venv_py" -c "import fastapi, uvicorn, httpx" >/dev/null 2>&1; then
    echo "▶ Installing gateway dependencies…"
    "$venv_py" -m pip install --quiet --upgrade pip
    "$venv_py" -m pip install --quiet -e ".[server]"
  fi
}

port_listener() {
  local port="$1" pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  printf '%s' "${pids%%$'\n'*}"
}

# The recorded pid is ours only while that process is this repo's gateway.
# A recycled pid (same number, different program) is not signaled.
is_our_gateway() {
  local pid="$1" root cmd cwd
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  if ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  root="$(gateway_root)"
  if [ -r "/proc/$pid/cmdline" ]; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  else
    cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | sed -n '1p')"
  fi
  cwd="$(physical_dir "$cwd")"
  [ "$cwd" = "$root" ] || return 1
  case "$cmd" in
    *agent_cli_bridge.gateway*) return 0 ;;
    *) return 1 ;;
  esac
}

read_recorded_pid() {
  local file pid
  file="$(pid_file)"
  [ -f "$file" ] || return 1
  pid="$(tr -d '[:space:]' < "$file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$pid"
}

record_pid() {
  printf '%s\n' "$1" > "$(pid_file)"
}

forget_pid() {
  rm -f "$(pid_file)"
}

terminate_our_gateway() {
  local pid="$1" i
  is_our_gateway "$pid" || return 0
  kill -TERM "$pid" 2>/dev/null || true
  i=0
  while [ "$i" -lt 10 ]; do
    is_our_gateway "$pid" || return 0
    sleep 0.2
    i=$((i + 1))
  done
  kill -KILL "$pid" 2>/dev/null || true
  sleep 0.2
  is_our_gateway "$pid" && return 1
  return 0
}

# Our own previous listener can be replaced. Anyone else keeps the port.
refuse_stranger_on_port() {
  local port="$1" holder
  holder="$(port_listener "$port")"
  [ -n "$holder" ] || return 0
  if ! is_our_gateway "$holder"; then
    echo "Port $port is used by another program and was left alone."
    exit 1
  fi
  echo "▶ Replacing the gateway already listening on port ${port}…"
  terminate_our_gateway "$holder" || true
  holder="$(port_listener "$port")"
  if [ -n "$holder" ]; then
    echo "Port $port is used by another program and was left alone."
    exit 1
  fi
}

stop_recorded_gateway() {
  local pid i
  pid="$(read_recorded_pid || true)"
  if [ -z "$pid" ] || ! is_our_gateway "$pid"; then
    forget_pid
    echo "AgentCliBridge gateway is not running."
    exit 0
  fi
  kill -TERM "$pid" 2>/dev/null || true
  i=0
  while [ "$i" -lt 5 ]; do
    if ! is_our_gateway "$pid"; then
      forget_pid
      echo "Stopped."
      exit 0
    fi
    sleep 1
    i=$((i + 1))
  done
  if ! is_our_gateway "$pid"; then
    forget_pid
    echo "Stopped."
    exit 0
  fi
  echo "AgentCliBridge gateway (pid $pid) is still running."
  exit 1
}

kill_recorded_gateway() {
  local pid
  pid="$(read_recorded_pid || true)"
  if [ -z "$pid" ] || ! is_our_gateway "$pid"; then
    forget_pid
    echo "AgentCliBridge gateway is not running."
    exit 0
  fi
  kill -KILL "$pid" 2>/dev/null || true
  forget_pid
  echo "Killed."
  exit 0
}

main() {
  local root python venv_py brew_bin
  root="$(gateway_root)"
  cd "$root"
  load_dotenv "$root/.env"
  PORT="${PORT:-4747}"
  export PORT
  refuse_stranger_on_port "$PORT"
  python="$(find_python || true)"
  if [ -z "$python" ]; then
    brew_bin="$(command -v brew 2>/dev/null || true)"
    if [ -n "$brew_bin" ]; then
      echo "▶ Python 3.11+ not found — installing via Homebrew…"
      "$brew_bin" install python@3.13
      python="$(find_python || true)"
    fi
  fi
  [ -n "$python" ] || { echo "ERROR: Python 3.11+ is required (brew install python@3.13)"; exit 1; }
  venv_py="$root/venv/bin/python3"
  ensure_venv "$python" "$venv_py"
  echo "▶ AgentCliBridge gateway → http://127.0.0.1:$PORT/v1  (Ctrl+C to stop)"
  record_pid "$$"
  exec "$venv_py" -m agent_cli_bridge.gateway
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
