"""Windows helper tools (``winget``, ``npm.cmd``) found by full path.

A background process (a service, ``pythonw``) starts with a bare PATH, and a bare name on a PATH
is what another program can shadow: the update and uninstall plans carry the resolved path.
"""

import os
import shutil
from collections.abc import Callable
from pathlib import PureWindowsPath

# Where each tool lives when the PATH does not reach it: (environment variable, folder below it).
_WINDOWS_TOOL_PLACES = {
    "winget": (("LOCALAPPDATA", r"Microsoft\WindowsApps\winget.exe"),),
    "npm.cmd": (
        ("ProgramFiles", r"nodejs\npm.cmd"),
        ("ProgramFiles(x86)", r"nodejs\npm.cmd"),
        ("APPDATA", r"npm\npm.cmd"),
    ),
}


def first_executable(paths: list[str]) -> str:
    return next((path for path in paths if path and os.path.isfile(path) and os.access(path, os.X_OK)), "")


def windows_places(variable: str, relative: str) -> list[str]:
    """``%variable%\\relative`` when that environment variable is set: a Windows tool's fixed
    place, for a background process whose PATH does not reach it."""
    root = os.environ.get(variable, "")
    return [str(PureWindowsPath(root) / relative)] if root else []


def windows_tool(
    name: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    find: Callable[[list[str]], str] = first_executable,
) -> str:
    """The full path of ``winget`` or ``npm.cmd``; the bare ``name`` when neither the PATH nor its
    usual folders have it (the run then fails with a clear "could not start")."""
    places = [path for variable, relative in _WINDOWS_TOOL_PLACES.get(name, ()) for path in windows_places(variable, relative)]
    return which(name) or find(places) or name
