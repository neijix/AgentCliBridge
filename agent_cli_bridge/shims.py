"""Launcher shims: put a Python module on an agent CLI's PATH under a plain command name.

An agent reaches a local tool through its shell (``d3skwebscout search "…"``) rather than an
MCP server. The tool lives in its own checkout and venv, so the command name has to resolve to
``<that venv's python> -m <module>``. ``ensure_shim`` writes a tiny launcher for it into a
per-user folder that holds **only** these shims, and ``with_path`` puts that folder first on the
CLI process's PATH — the CLI's shell tool inherits it (checked live with Claude Code, see
KNOWLEDGE.md "WebScout through the shell").

- POSIX: ``<folder>/<name>``, ``#!/bin/sh`` + ``exec "<python>" -m <module> "$@"``, mode 0755.
- Windows: ``<folder>\\<name>.cmd`` (``@"<python>" -m <module> %*``) for cmd / PowerShell, plus an
  extension-less ``sh`` launcher next to it for Git Bash (Claude Code's shell on Windows), which
  does not run ``.cmd`` files by their bare name.

A shim is rewritten only when its content changes, atomically (temp file + ``os.replace``), so
concurrent turns never see a half-written launcher. Generic on purpose: D3SKHAND uses the same
helpers for its own ``d3skhand`` command.

    folder = ensure_shim("d3skwebscout", "/path/to/.venv/bin/python", "d3skwebscout")
    env = with_path(os.environ, folder)
"""
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

APP_FOLDER = "agent-cli-bridge"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def default_folder(env: Mapping[str, str] | None = None, *, is_windows: bool | None = None) -> Path:
    """The per-user shim folder: ``%LOCALAPPDATA%\\agent-cli-bridge\\bin`` on Windows,
    ``$XDG_CACHE_HOME/agent-cli-bridge/bin`` (default ``~/.cache``) elsewhere."""
    values = os.environ if env is None else env
    windows = os.name == "nt" if is_windows is None else is_windows
    if windows:
        base = values.get("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = values.get("XDG_CACHE_HOME", "").strip()
        root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / APP_FOLDER / "bin"


def _check(name: str, module: str, python: str) -> None:
    if not _SAFE_NAME.match(name):
        raise ValueError(f"unsafe shim name {name!r}")
    if not all(_SAFE_NAME.match(part) for part in module.split(".")):
        raise ValueError(f"unsafe module name {module!r}")
    if not python or any(ch in python for ch in '"\n\r\0'):
        raise ValueError(f"unusable python path {python!r}")


def _sh_quote(path: str) -> str:
    """``path`` inside double quotes for /bin/sh (``\\``, ``$`` and backticks escaped)."""
    return '"' + re.sub(r'([\\$`])', r"\\\1", path) + '"'


def posix_shim(python: str, module: str) -> str:
    return f'#!/bin/sh\nexec {_sh_quote(python)} -m {module} "$@"\n'


def windows_cmd_shim(python: str, module: str) -> str:
    # In a .cmd file a literal % is written %%; the path cannot hold a double quote.
    return f'@"{python.replace("%", "%%")}" -m {module} %*\r\n'


def git_bash_shim(python: str, module: str) -> str:
    # Git Bash takes C:/… paths; forward slashes avoid any backslash escaping question.
    return posix_shim(python.replace("\\", "/"), module)


def shim_files(name: str, python: str, module: str, *, is_windows: bool) -> dict[str, str]:
    """File name → content of the launcher(s) ``ensure_shim`` writes for this OS."""
    _check(name, module, python)
    if is_windows:
        return {f"{name}.cmd": windows_cmd_shim(python, module), name: git_bash_shim(python, module)}
    return {name: posix_shim(python, module)}


def _write_if_changed(path: Path, content: str, mode: int) -> bool:
    data = content.encode("utf-8")
    try:
        if path.read_bytes() == data and (os.name == "nt" or path.stat().st_mode & 0o777 == mode):
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def ensure_shim(
    name: str,
    python: Path | str,
    module: str,
    *,
    folder: Path | str | None = None,
    is_windows: bool | None = None,
) -> Path:
    """Write (or keep) the ``name`` launcher for ``python -m module``; returns the shim folder.

    ``folder`` defaults to ``default_folder()``; it must hold only shims, since it goes first on
    the CLI's PATH. Raises ``ValueError`` on an unsafe name/module/path and ``OSError`` when the
    folder cannot be written.
    """
    windows = os.name == "nt" if is_windows is None else is_windows
    target = Path(folder) if folder is not None else default_folder(is_windows=windows)
    files = shim_files(name, str(python), module, is_windows=windows)
    target.mkdir(parents=True, exist_ok=True)
    for file_name, content in files.items():
        _write_if_changed(target / file_name, content, 0o755)
    return target


def path_key(env: Mapping[str, str], *, is_windows: bool | None = None) -> str:
    """The name ``env`` keeps PATH under: on Windows whatever its case (``Path``), else ``PATH``."""
    if not (os.name == "nt" if is_windows is None else is_windows):
        return "PATH"
    return next((k for k in env if k.upper() == "PATH"), "PATH")


def with_path(
    env: Mapping[str, str], folder: Path | str, *, is_windows: bool | None = None
) -> dict[str, str]:
    """A copy of ``env`` with ``folder`` first on PATH (an earlier copy of it removed).

    On Windows the existing key is found whatever its case (``Path``, ``PATH``) and kept.
    """
    windows = os.name == "nt" if is_windows is None else is_windows
    result = dict(env)
    key = path_key(result, is_windows=windows)
    separator = ";" if windows else ":"
    entry = str(folder)
    same = (lambda a, b: a.lower() == b.lower()) if windows else (lambda a, b: a == b)
    rest = [p for p in result.get(key, "").split(separator) if p and not same(p, entry)]
    result[key] = separator.join([entry, *rest])
    return result
