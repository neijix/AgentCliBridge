"""Windows: launch what a ``.cmd`` CLI launcher runs, never the launcher itself.

``CreateProcess`` cannot run a ``.cmd`` / ``.bat`` file: Windows hands it to ``cmd.exe /c``, which
re-reads the whole command line with its own rules. Python quotes argv for the C runtime, not for
cmd.exe, so a turn's argv — prompt text, ``--settings`` JSON, a system prompt — loses its quotes,
splits on ``&`` / ``|``, redirects on ``<`` / ``>``, expands ``%VAR%`` and stops at the first line
break. A prompt can even run commands of its own (the "BatBadBut" class of issue).

Several CLIs install exactly such a launcher (seen 2026-10-09): npm's cmd-shim for Gemini, Grok
and OpenCode (``"%_prog%" "%dp0%\\…\\cli.js" %*`` or ``"%dp0%\\…\\tool.exe" %*``), and Cursor
Agent's ``agent.cmd``, which runs ``cursor-agent.ps1`` through PowerShell (whose ``$args``
forwarding drops embedded quotes too), which runs ``versions\\<latest>\\node.exe index.js``.

``direct_launch`` swaps the launcher for that real command, so the argv reaches the program
untouched; a target that is itself a launcher is resolved again (a few levels deep). A launcher it
cannot see through is still run when no argument holds a character cmd.exe would act on;
otherwise the turn is refused with ``UnsafeLauncherError`` rather than sent mangled (or worse)
through cmd.exe.

Cursor Agent: among its ``versions`` folders the newest build wins, time of day included, and an
incomplete newest folder falls back to the previous one; ``cursor-agent.ps1`` compares dates only
and fails on an incomplete folder. Both pick the same folder on every install seen so far.
"""
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

LAUNCHER_SUFFIXES = (".cmd", ".bat")
MAX_DEPTH = 4  # launchers that run launchers
# Characters CreateProcess takes on a command line, its final NUL included. Past it, Windows
# answers ERROR_FILENAME_EXCED_RANGE (206), which Python raises as FileNotFoundError.
COMMAND_LINE_LIMIT = 32_767
# Linux MAX_ARG_STRLEN: the most bytes one argument may take, its NUL included.
LINUX_ARG_LIMIT = 131_072
# Characters cmd.exe re-reads on a command line (quotes, operators, redirections, variables,
# delayed expansion, its escape, the parentheses of an IF / FOR block) and the line breaks it
# stops at.
_CMD_SPECIAL = re.compile(r'["&|<>^%!()\r\n]')
# npm cmd-shim: the line that runs the program, e.g. `… & "%_prog%"  "%dp0%\node_modules\x\cli.js" %*`
_RUN_LINE = re.compile(r"(?:^|&)\s*@?((?:\"[^\"]*\"\s*)+)%\*\s*$")
_QUOTED = re.compile(r'"([^"]*)"')
# npm cmd-shim's interpreter: `SET "_prog=%dp0%\node.exe"` (beside the shim) else `SET "_prog=node"`.
_PROG = re.compile(r'SET\s+"_prog=([^"]*)"', re.IGNORECASE)
# Cursor Agent version folders: 2026.10.01-e373342 or 2026.10.01-14-05-09-e373342.
_CURSOR_VERSION = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-(\d{2})-(\d{2})-(\d{2}))?-[a-f0-9]+$", re.IGNORECASE
)

Which = Callable[[str], str | None]


class UnsafeLauncherError(ValueError):
    """A ``.cmd`` launcher this module cannot see through, with argv cmd.exe would rewrite."""


def is_launcher(binary: str) -> bool:
    # CreateProcess still hands `x.cmd.` and `x.cmd ` to cmd.exe (CVE-2024-43402).
    return binary.rstrip(" .").lower().endswith(LAUNCHER_SUFFIXES)


def _expand(token: str, folder: Path) -> str | None:
    """``%dp0%`` / ``%~dp0`` → the launcher's folder; None when another variable is left."""
    for variable in ("%dp0%", "%~dp0"):
        if token.startswith(variable):
            # Split on both separators: off Windows a backslash is part of a file name.
            parts = [part for part in re.split(r"[\\/]", token[len(variable):]) if part]
            token = str(folder.joinpath(*parts))
    return None if "%" in token or "!" in token else token


def _interpreter(text: str, folder: Path, which: Which) -> str | None:
    """What ``%_prog%`` is: a ``SET "_prog=…"`` path that exists beside the shim, else the bare
    name it falls back to, looked up on the child's PATH (by full path)."""
    names = _PROG.findall(text)
    for name in names:
        path = _expand(name, folder)
        if path and ("\\" in path or "/" in path) and Path(path).is_file():
            return path
    for name in reversed(names):
        if name and "%" not in name and "\\" not in name and "/" not in name:
            return which(name)
    return None


def npm_shim_argv(text: str, folder: Path, which: Which = shutil.which) -> list[str] | None:
    """The command an npm cmd-shim (or a one-line ``@"<exe>" "<script>" %*`` launcher) runs.

    ``%dp0%`` / ``%~dp0`` are the launcher's folder; ``%_prog%`` is its interpreter (see
    ``_interpreter``). None when a token still holds a variable or the program is missing.
    """
    for line in reversed(text.splitlines()):
        match = _RUN_LINE.search(line.strip())
        if match:
            break
    else:
        return None
    argv = []
    for token in _QUOTED.findall(match.group(1)):
        resolved = _interpreter(text, folder, which) if token == "%_prog%" else _expand(token, folder)
        if not resolved:
            return None
        argv.append(resolved)
    if not argv or not Path(argv[0]).is_file():
        return None
    return argv


def _cursor_version_key(name: str) -> tuple[int, ...] | None:
    match = _CURSOR_VERSION.match(name)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def cursor_agent_argv(launcher: Path) -> list[str] | None:
    """Cursor Agent's ``agent.cmd`` / ``cursor-agent.cmd``: the ``node.exe index.js`` its
    ``cursor-agent.ps1`` would run (beside it, else the newest complete ``versions\\<version>``)."""
    folder = launcher.parent
    if not (folder / "cursor-agent.ps1").is_file():
        return None
    candidates = [folder]
    versions = folder / "versions"
    if versions.is_dir():
        dated = [(key, path) for path in versions.iterdir() if (key := _cursor_version_key(path.name))]
        candidates += [path for _, path in sorted(dated, reverse=True)]
    for candidate in candidates:
        node, script = candidate / "node.exe", candidate / "index.js"
        if node.is_file() and script.is_file():
            return [str(node), str(script)]
    return None


def _env_which(env: Mapping[str, str]) -> Which:
    path = next((value for key, value in env.items() if key.upper() == "PATH"), None)
    return lambda name: shutil.which(name, path=path)


def _resolve(launcher: Path, env: Mapping[str, str]) -> tuple[list[str], dict[str, str]] | None:
    cursor = cursor_agent_argv(launcher)
    if cursor is not None:
        overlay = {"CURSOR_INVOKED_AS": launcher.name}  # agent.cmd sets it unconditionally
        local_app = env.get("LOCALAPPDATA")
        if local_app and not env.get("NODE_COMPILE_CACHE"):
            overlay["NODE_COMPILE_CACHE"] = str(Path(local_app) / "cursor-compile-cache")
        return cursor, overlay
    text = launcher.read_text(encoding="utf-8", errors="replace")
    target = npm_shim_argv(text, launcher.parent, _env_which(env))
    return (target, {}) if target is not None else None


def direct_launch(
    argv: list[str], env: Mapping[str, str] | None = None, *, is_windows: bool | None = None
) -> tuple[list[str], dict[str, str]]:
    """``argv`` with a ``.cmd`` / ``.bat`` launcher swapped for the command it runs, plus what
    that launcher would have set in ``env`` (the child's environment; default ``os.environ``).
    Unchanged off Windows and for real executables.

    Raises ``UnsafeLauncherError`` for a launcher it cannot see through when an argument holds a
    character cmd.exe would act on.
    """
    windows = os.name == "nt" if is_windows is None else is_windows
    child_env = os.environ if env is None else env
    overlay: dict[str, str] = {}
    for _ in range(MAX_DEPTH):
        if not windows or not argv or not is_launcher(argv[0]):
            return argv, overlay
        try:
            resolved = _resolve(Path(argv[0]), {**child_env, **overlay})
        except OSError:
            resolved = None
        if resolved is None:
            break
        target, launcher_env = resolved
        argv = [*target, *argv[1:]]
        overlay.update(launcher_env)
    if not is_launcher(argv[0]):
        return argv, overlay
    if any(_CMD_SPECIAL.search(arg) for arg in argv[1:]):
        raise UnsafeLauncherError(
            f"{Path(argv[0]).name} is a Windows batch launcher, and cmd.exe would rewrite this "
            "turn's arguments (quotes, & | < > ^ % ! ( ), line breaks). Point the bridge at the "
            "program it runs instead (the binary= setting or PATH)."
        )
    return argv, overlay


def command_line_length(argv: list[str], *, is_windows: bool | None = None) -> int:
    """UTF-16 units ``argv`` takes on a Windows command line; 0 off Windows (no such limit)."""
    windows = os.name == "nt" if is_windows is None else is_windows
    if not windows:
        return 0
    return len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2 + 1  # an emoji counts 2


def is_too_long(argv: list[str], *, is_windows: bool | None = None, is_linux: bool | None = None) -> bool:
    """Whether the OS would refuse to start ``argv``.

    Windows: its command line is over ``COMMAND_LINE_LIMIT``. Linux: one argument reaches
    ``LINUX_ARG_LIMIT`` (``Argument list too long``), e.g. a long page as Claude's prompt.
    """
    if command_line_length(argv, is_windows=is_windows) > COMMAND_LINE_LIMIT:
        return True
    linux = sys.platform.startswith("linux") if is_linux is None else is_linux
    return linux and any(len(arg.encode("utf-8", "surrogatepass")) >= LINUX_ARG_LIMIT for arg in argv)
