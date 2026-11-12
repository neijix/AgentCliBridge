"""Remove a packaged install: stop the gateway, drop the start at login, delete the folder.

The settings folder is kept unless ``--remove-settings`` asks otherwise. Nothing is deleted
until ``install.json`` and the snapshot manifest say the folder really is an install.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

from bridge_installer import DISPLAY_NAME
from bridge_installer.layout import Answers, Layout, SetupError, answers_from_record, read_record
from bridge_installer.manifest import ManifestError, read_manifest
from bridge_installer.system import Runner, disable_autostart, remove_tree, run_command, run_gateway_script


def verified_answers(layout: Layout) -> Answers:
    record = read_record(layout)
    if record is None:
        raise SetupError(f"{layout.root} is not an {DISPLAY_NAME} install (no install.json): nothing removed")
    try:
        if layout.app.exists() and read_manifest(layout.app) is None:
            raise SetupError(f"{layout.app} holds no {DISPLAY_NAME} manifest: nothing removed")
    except ManifestError as exc:
        raise SetupError(f"{exc}: nothing removed") from exc
    return answers_from_record(layout, record)


def _is_protected(folder: Path, root: Path) -> bool:
    """A settings folder never removed: the filesystem root, the home folder, or above the install."""
    return folder == Path(folder.anchor) or folder == Path.home() or folder in root.parents or folder == root


def _remove_except(folder: Path, keep: Path | None) -> list[Path]:
    """Delete everything in ``folder`` but ``keep`` (and the folders leading to it); the leftovers."""
    left: list[Path] = []
    for entry in folder.iterdir():
        if keep is not None and entry == keep:
            continue
        if keep is not None and entry in keep.parents and entry.is_dir() and not entry.is_symlink():
            left += _remove_except(entry, keep)
            continue
        if not remove_tree(entry):
            left.append(entry)
    return left


def _defer_windows(paths: list[Path], root: Path) -> None:
    """Windows keeps a running python.exe locked: a detached cmd removes the leftovers once it exits."""
    sys32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
    cmd_exe = sys32 / "cmd.exe"
    ping_exe = sys32 / "ping.exe"
    steps = " & ".join(f'rmdir /s /q "{path}"' if path.is_dir() else f'del /f /q "{path}"' for path in paths)
    command = f'"{ping_exe}" -n 4 127.0.0.1 >nul & {steps} & rmdir "{root}"'
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(cmd_exe), "/d", "/c", command], cwd=str(root.parent), creationflags=flags, close_fds=True)  # noqa: S603


def uninstall(layout: Layout, *, remove_settings: bool = False, runner: Runner = run_command) -> int:
    answers = verified_answers(layout)
    root, settings = layout.root, answers.settings_dir
    print(f"Removing {DISPLAY_NAME} from {root}")
    disable_autostart(layout, runner=runner)
    if not run_gateway_script(layout, "stop", runner=runner):
        run_gateway_script(layout, "kill", runner=runner)
    inside = root in settings.parents
    keep = settings if inside and not remove_settings else None
    left = _remove_except(root, keep)
    if remove_settings and not inside and settings.exists():
        if _is_protected(settings, root):
            print(f"note: the settings folder {settings} was left alone (it is not a folder the setup may delete)")
        elif not remove_tree(settings):
            left.append(settings)
    elif not remove_settings:
        print(f"Kept the settings folder {settings} (--remove-settings deletes it)")
    if keep is None:
        with contextlib.suppress(OSError):
            root.rmdir()
    if left and sys.platform == "win32":
        _defer_windows(left, root)
        print("The files still in use are removed a few seconds after this window closes.")
        return 0
    if left:
        print(f"Could not remove: {', '.join(map(str, left))}", file=sys.stderr)
        return 1
    print(f"{DISPLAY_NAME} is removed.")
    return 0
