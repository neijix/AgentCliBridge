#!/bin/sh
# AgentCliBridge setup, step one (macOS / Linux). Sits beside the snapshot in the setup folder:
#   <setup folder>/setup.sh  setup.ps1  app/ (the snapshot)
# It asks the install folder first, finds uv or fetches it, makes sure Python 3.12 is there, then
# hands every argument to the setup wizard (python -m bridge_installer, run from <setup>/app).
# The twin is setup.ps1 (Windows): the two behave the same, keep them in step.
#
# uv, Python 3.12 and temporary files go in the install folder (--dir, else
# AGENTCLIBRIDGE_SETUP_DIR, else one prompt with no default): <folder>/uv and <folder>/temp,
# never the user profile. A folder that is non-empty and is not an AgentCliBridge install is
# refused before anything is written.
set -eu

MANIFEST_NAME="agentclibridge-snapshot.json"   # bridge_installer MANIFEST_NAME (a test checks they match)
PYTHON_VERSION="3.12"                           # bridge_installer PYTHON_VERSION
UV_INSTALL_SH="https://astral.sh/uv/install.sh"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# An absolute path: the wizard runs in the snapshot folder, so a relative one is taken from where
# the user ran this script.
absolute() {
  # shellcheck disable=SC2088  # a literal "~" typed at the prompt, not one the shell expanded
  case "$1" in
    "~") printf '%s\n' "$HOME" ;;
    "~/"*) printf '%s\n' "$HOME/${1#"~/"}" ;;
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$START_DIR/$1" ;;
  esac
}

START_DIR="$(pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/app"

[ -f "$APP/bridge_installer/__main__.py" ] ||
  die "$APP holds no AgentCliBridge snapshot: run setup.sh from the setup folder it came in"

# A macOS installer runs with a minimal PATH: look where uv usually lives too.
if [ "$(uname -s)" = "Darwin" ]; then
  PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"
  export PATH
fi

# Every argument passes through, except that a --dir value becomes absolute.
dir=""
want_help=""
skip_folder=""
pending=""
count=$#
while [ "$count" -gt 0 ]; do
  arg="$1"
  shift
  count=$((count - 1))
  if [ -n "$pending" ]; then
    case "$arg" in
      -*) die "--dir needs a folder, not $arg" ;;
      *) ;;
    esac
    arg="$(absolute "$arg")"
    dir="$arg"
    pending=""
  else
    case "$arg" in
      --dir) pending=1 ;;
      --dir=*) arg="--dir=$(absolute "${arg#--dir=}")"; dir="${arg#--dir=}" ;;
      -h | --help) want_help=1 ;;
      --uninstall | --update) skip_folder=1 ;;
      *) ;;
    esac
  fi
  set -- "$@" "$arg"
done
[ -z "$pending" ] || die "--dir needs a folder"

# The wizard's help needs no toolchain and no folder: nothing is fetched or written.
if [ -n "$want_help" ]; then
  PYTHON="$(command -v python3.12 || command -v python3 || true)"
  [ -n "$PYTHON" ] || die "Python 3 is needed to show the help"
  PYTHONPATH="$APP"
  PYTHONDONTWRITEBYTECODE=1
  export PYTHONPATH PYTHONDONTWRITEBYTECODE
  cd "$APP"
  exec "$PYTHON" -m bridge_installer "$@"
fi

# The folder first: it is refused here, before anything is written, and uv and Python go into it.
if [ -z "$dir" ]; then
  if [ -n "${AGENTCLIBRIDGE_SETUP_DIR:-}" ]; then
    dir="$(absolute "$AGENTCLIBRIDGE_SETUP_DIR")"
  elif [ -t 0 ]; then
    printf 'Install folder (no default): '
    IFS= read -r answer || answer=""
    [ -n "$answer" ] || die "no install folder given (--dir <folder> or AGENTCLIBRIDGE_SETUP_DIR)"
    dir="$(absolute "$answer")"
  else
    die "the install folder is required: --dir <folder> or AGENTCLIBRIDGE_SETUP_DIR"
  fi
  set -- "$@" --dir "$dir"
fi
if [ -e "$dir" ] && [ ! -d "$dir" ]; then
  die "$dir exists and is not a folder"
fi
case "$dir/" in
  "$HERE"/*) die "$dir is inside the setup folder ($HERE): choose another folder" ;;
  *) ;;
esac
if [ -z "$skip_folder" ] && [ -d "$dir" ] && [ ! -f "$dir/app/$MANIFEST_NAME" ]; then
  # Only this script's own uv/ and temp/ (a run that stopped before the wizard) leave it new, as
  # bridge_installer/apply.py SETUP_BOOTSTRAP says.
  for entry in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    case "${entry##*/}" in
      uv | temp) [ -d "$entry" ] && [ ! -L "$entry" ] && continue ;;
      *) ;;
    esac
    die "$dir is not empty and is not an AgentCliBridge install (no app/$MANIFEST_NAME): choose an empty or new folder"
  done
fi
ROOT="$dir"
BIN="$ROOT/uv/bin"
TEMP_DIR="$ROOT/temp"

# Run a command with uv and the temp pinned at ROOT (bridge_installer/apply.py uv_env), Python
# only from uv's own folder.
uv_run() {
  (
    unset UV_PYTHON UV_NO_MANAGED_PYTHON UV_PYTHON_DOWNLOADS UV_SYSTEM_PYTHON UV_PROJECT VIRTUAL_ENV
    TMP="$TEMP_DIR"
    TEMP="$TEMP_DIR"
    TMPDIR="$TEMP_DIR"
    export TMP TEMP TMPDIR
    UV_CACHE_DIR="$ROOT/uv/cache"
    UV_PYTHON_INSTALL_DIR="$ROOT/uv/python"
    UV_PYTHON_BIN_DIR="$BIN"
    UV_TOOL_DIR="$ROOT/uv/tools"
    UV_TOOL_BIN_DIR="$BIN"
    UV_PYTHON_PREFERENCE="only-managed"
    export UV_CACHE_DIR UV_PYTHON_INSTALL_DIR UV_PYTHON_BIN_DIR UV_TOOL_DIR UV_TOOL_BIN_DIR UV_PYTHON_PREFERENCE
    PATH="$BIN:$PATH"
    export PATH
    exec "$@"
  )
}

echo "AgentCliBridge setup: uv and Python $PYTHON_VERSION are kept in $ROOT/uv, temporary files in $TEMP_DIR."
echo "  (nothing is written to your user profile)"
mkdir -p "$TEMP_DIR" || die "cannot create $TEMP_DIR"

UV=""
if [ -x "$BIN/uv" ]; then
  UV="$BIN/uv"
elif command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
fi

if [ -z "$UV" ]; then
  echo "uv not found: fetching it from $UV_INSTALL_SH into $BIN"
  if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL -o "$2" "$1"; }
  elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -q -O "$2" "$1"; }
  else
    die "uv is missing and neither curl nor wget is available to fetch it"
  fi
  # The script goes to a file first (a failed download runs nothing), then runs with
  # UV_UNMANAGED_INSTALL at ROOT: no install receipt in the user's config folder, no PATH edit.
  scratch="$(mktemp -d "$TEMP_DIR/uv-install.XXXXXX")" || die "cannot create a folder in $TEMP_DIR"
  trap 'rm -rf "$scratch"' EXIT
  fetch "$UV_INSTALL_SH" "$scratch/uv-install.sh" || die "could not download $UV_INSTALL_SH"
  UV_UNMANAGED_INSTALL="$BIN" uv_run sh "$scratch/uv-install.sh" || die "uv's installer failed"
  rm -rf "$scratch"
  trap - EXIT
  [ -x "$BIN/uv" ] || die "uv's installer ran but $BIN/uv does not exist"
  UV="$BIN/uv"
else
  echo "uv found: $UV (nothing to download)"
fi

# --system skips any virtualenv in the current folder; uv_run limits uv to its managed Pythons.
if ! uv_run "$UV" python find --system "$PYTHON_VERSION" >/dev/null 2>&1; then
  echo "Python $PYTHON_VERSION not found: installing it with uv into $ROOT/uv/python"
  uv_run "$UV" python install "$PYTHON_VERSION" || die "uv could not install Python $PYTHON_VERSION"
fi
PYTHON="$(uv_run "$UV" python find --system "$PYTHON_VERSION")" ||
  die "uv found no managed Python $PYTHON_VERSION"

# The wizard gets no uv or temp set (the gateway it starts must not inherit them), only the
# snapshot on its path and the uv to build the venv with; it writes no bytecode into the snapshot.
AGENT_CLI_BRIDGE_SETUP_UV="$UV"
PYTHONPATH="$APP"
PYTHONDONTWRITEBYTECODE=1
export AGENT_CLI_BRIDGE_SETUP_UV PYTHONPATH PYTHONDONTWRITEBYTECODE
cd "$APP"
exec "$PYTHON" -m bridge_installer "$@"
