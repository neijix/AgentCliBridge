"""Install or upgrade: copy the snapshot in, build the venv with uv, write the files, start.

An upgrade (``install.json`` already there) stops the gateway first, swaps ``app/`` in one rename,
keeps the owner's own ``gateway.env`` lines, and starts the gateway again. Everything lands under
the install folder; the settings folder is wherever the owner chose (``<install>/config`` by
default), and the start at login (``system.py``) is the one write outside both.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from bridge_installer import DISPLAY_NAME, SETUP_UV_ENV
from bridge_installer.layout import (
    Answers,
    Layout,
    SetupError,
    answers_from_record,
    gateway_env_text,
    read_record,
    write_launchers,
    write_record,
    write_text_atomic,
)
from bridge_installer.manifest import Manifest, ManifestError, read_manifest
from bridge_installer.system import (
    Runner,
    autostart_target,
    disable_autostart,
    enable_autostart,
    port_answers,
    remove_tree,
    run_command,
    run_gateway_script,
    stop_autostarted,
    wait_for_port,
)

SOURCE = Path(__file__).resolve().parents[1]  # the snapshot this wizard runs from
SETUP_BOOTSTRAP = ("uv", "temp")  # what setup.sh / setup.ps1 write before the wizard runs
_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc")


def find_uv(layout: Layout, explicit: Path | None = None) -> Path:
    """``--uv``, else the uv the setup script handed over, else the install's own, else PATH."""
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    handed = os.environ.get(SETUP_UV_ENV, "").strip()
    for candidate in (explicit, Path(handed) if handed else None, layout.uv_dir / "bin" / exe):
        if candidate is not None and candidate.is_file():
            return candidate
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise SetupError("uv is not found: run the setup script (setup.sh / setup.ps1), or pass --uv <path>")


def uv_env(layout: Layout) -> dict[str, str]:
    """uv pinned to the install folder: its cache, its Pythons, its temp, the install's venv."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("UV_") and key != "VIRTUAL_ENV"}
    temp = str(layout.temp)
    env.update(
        UV_PROJECT_ENVIRONMENT=str(layout.venv),
        UV_CACHE_DIR=str(layout.uv_dir / "cache"),
        UV_PYTHON_INSTALL_DIR=str(layout.uv_dir / "python"),
        UV_PYTHON_BIN_DIR=str(layout.uv_dir / "bin"),
        UV_TOOL_DIR=str(layout.uv_dir / "tools"),
        UV_TOOL_BIN_DIR=str(layout.uv_dir / "bin"),
        TMPDIR=temp, TMP=temp, TEMP=temp,
    )
    return env


def sync_venv(layout: Layout, uv: Path, python: Path, *, runner: Runner = run_command) -> None:
    """``uv sync``: the locked gateway dependencies (the ``server`` extra) into ``<install>/venv``."""
    argv = [str(uv), "sync", "--frozen", "--extra", "server", "--python", str(python)]
    print(f"Building the gateway's Python environment in {layout.venv} …")
    done = runner(argv, cwd=str(layout.app), env=uv_env(layout))
    if done.returncode != 0:
        raise SetupError(f"uv sync failed (exit {done.returncode}); the install folder is unchanged otherwise")


def check_folder(layout: Layout, source: Path) -> dict[str, object] | None:
    """The previous install record, or ``None`` for a new folder; ``SetupError`` for a foreign one."""
    root = layout.root
    if root.exists() and not root.is_dir():
        raise SetupError(f"{root} exists and is not a folder")
    is_own = source == layout.app or layout.temp in source.parents  # a re-run, or an update's download
    if not is_own and (root == source or source in root.parents or root in source.parents):
        raise SetupError(f"{root} overlaps the snapshot the setup runs from ({source}): choose another folder")
    record = read_record(layout)
    if record is not None or not root.exists():
        return record
    strangers = [entry.name for entry in root.iterdir() if entry.name not in SETUP_BOOTSTRAP or not entry.is_dir()]
    if strangers:
        raise SetupError(f"{root} is not empty and is not an {DISPLAY_NAME} install: choose an empty or new folder")
    return None


def swap_app(source: Path, layout: Layout) -> None:
    """Copy the snapshot to ``app.new``, then one rename puts it in place of ``app``."""
    if source.resolve() == layout.app.resolve():
        return
    staged, old = layout.root / "app.new", layout.root / "app.old"
    for leftover in (staged, old):
        remove_tree(leftover)
    shutil.copytree(source, staged, ignore=_IGNORED, symlinks=False)
    if layout.app.exists():
        os.replace(layout.app, old)
    os.replace(staged, layout.app)
    if not remove_tree(old):
        print(f"note: {old} could not be removed yet (a file in use); the next setup run removes it")


def make_folders(answers: Answers) -> None:
    layout = answers.layout
    for folder in (layout.root, layout.work, layout.shim_dir, layout.logs, layout.state, layout.temp, answers.settings_dir):
        folder.mkdir(parents=True, exist_ok=True)
    layout.data.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(layout.data, 0o700)  # tokens and the security log: the bridge home is private


def stop_previous(layout: Layout, previous: Answers | None, *, runner: Runner) -> None:
    if previous is None:
        return
    if previous.autostart:
        stop_autostarted(layout, runner=runner)
    if not run_gateway_script(layout, "stop", runner=runner):
        run_gateway_script(layout, "kill", runner=runner)


def install(
    answers: Answers,
    *,
    source: Path | None = None,
    uv: Path | None = None,
    python: Path | None = None,
    should_start: bool = True,
    runner: Runner = run_command,
    is_up: Callable[[int], bool] = port_answers,
) -> int:
    """Install or upgrade the snapshot at ``source`` into ``answers.root``; 0 on success."""
    layout = answers.layout
    source = SOURCE if source is None else source
    record = check_folder(layout, source)
    try:
        manifest = read_manifest(source)
    except ManifestError as exc:
        raise SetupError(f"the snapshot is damaged: {exc}") from exc
    if manifest is None:
        raise SetupError(f"{source} is not an {DISPLAY_NAME} snapshot (no manifest)")
    previous = answers_from_record(layout, record) if record is not None else None
    verb = "Upgrading" if previous else "Installing"
    print(f"{verb} {DISPLAY_NAME} {manifest.version} in {layout.root}")
    uv_path = find_uv(layout, uv)
    python_path = python or Path(sys.executable)
    stop_previous(layout, previous, runner=runner)
    if previous is not None and previous.autostart and not answers.autostart:
        disable_autostart(layout, runner=runner)
    make_folders(answers)
    swap_app(source, layout)
    sync_venv(layout, uv_path, python_path, runner=runner)
    _write_files(answers, manifest, python_path)
    return _start(answers, should_start=should_start, runner=runner, is_up=is_up)


def _write_files(answers: Answers, manifest: Manifest, python: Path) -> None:
    layout = answers.layout
    previous_env = layout.env_file.read_text(encoding="utf-8") if layout.env_file.is_file() else ""
    write_text_atomic(layout.env_file, gateway_env_text(answers, previous_env), mode=0o600)
    write_launchers(layout, python)
    write_record(answers, manifest)


def _start(answers: Answers, *, should_start: bool, runner: Runner, is_up: Callable[[int], bool]) -> int:
    layout = answers.layout
    launcher = "start.cmd" if sys.platform == "win32" else "start.sh"
    if answers.autostart:
        print(f"Start at login: writing {autostart_target(layout)}")
        enable_autostart(layout, runner=runner)
    elif not should_start:
        print(f"Installed. Start the gateway with {layout.root / launcher}")
        return 0
    else:
        run_gateway_script(layout, "start", runner=runner)
    url = f"http://127.0.0.1:{answers.port}/"
    if wait_for_port(answers.port, is_up=is_up):
        print(f"{DISPLAY_NAME} gateway answers on {url}")
        return 0
    print(f"The gateway did not answer on {url} yet: see {layout.logs / 'gateway.log'}", file=sys.stderr)
    return 1
