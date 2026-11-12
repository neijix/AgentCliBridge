"""Where a packaged install keeps each thing, and the files the wizard writes there.

``<install>/`` holds ``app/`` (the snapshot), ``venv/``, ``uv/`` (uv, Python, its cache),
``temp/``, ``config/`` (the default settings folder), ``data/`` (the bridge home: tokens, the
security log), ``work/`` (where the CLIs run), ``cache/bin`` (the shims), ``logs/``, ``state/``,
``gateway.env`` (read by ``app/start.sh`` and ``start.ps1`` in install mode), ``install.json``
(the answers) and the launchers (``start``, ``stop``, ``kill``, ``update``, ``uninstall``).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from bridge_installer import APP, DEFAULT_PORT, INSTALL_DIR_ENV
from bridge_installer.manifest import Manifest

RECORD_FORMAT = 1
# A path the env file, a systemd unit, a .cmd file or a LaunchAgent would have to escape.
UNSAFE_PATH_CHARS = '"#%$`\n\r'
# The keys the wizard owns in gateway.env; any other line the owner added is kept.
OWNED_ENV_KEYS = (
    "PORT", "AGENT_CLI_BRIDGE_HOME", "AGENT_CLI_BRIDGE_CONFIG_LOCAL", "AGENT_CLI_BRIDGE_SHIM_DIR",
    "BRIDGE_WORKDIR", "TMPDIR", "TMP", "TEMP",
)
POSIX_LAUNCHERS = ("start.sh", "stop.sh", "kill.sh", "update.sh", "uninstall.sh")
WINDOWS_LAUNCHERS = ("start.cmd", "stop.cmd", "kill.cmd", "update.cmd", "uninstall.cmd")
_ENV_KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


class SetupError(Exception):
    """The setup cannot go on; the message is the reason, printed as one line."""


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def app(self) -> Path:
        return self.root / "app"

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def uv_dir(self) -> Path:
        return self.root / "uv"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    @property
    def default_settings(self) -> Path:
        return self.root / "config"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def shim_dir(self) -> Path:
        return self.root / "cache" / "bin"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def env_file(self) -> Path:
        return self.root / "gateway.env"

    @property
    def record(self) -> Path:
        return self.root / "install.json"

    def venv_python(self, *, is_windows: bool | None = None) -> Path:
        windows = sys.platform == "win32" if is_windows is None else is_windows
        return self.venv / "Scripts" / "python.exe" if windows else self.venv / "bin" / "python3"


@dataclass(frozen=True)
class Answers:
    root: Path
    settings_dir: Path
    port: int
    autostart: bool

    @property
    def layout(self) -> Layout:
        return Layout(self.root)


def check_path(path: Path, what: str) -> Path:
    """``path`` made absolute, or ``SetupError`` when a launcher or the env file could not hold it."""
    text = str(path)
    if not text.strip() or text != text.strip():
        raise SetupError(f"the {what} has leading or trailing spaces: {text!r}")
    resolved = Path(os.path.abspath(Path(text).expanduser()))
    bad = sorted({char for char in str(resolved) if char in UNSAFE_PATH_CHARS})
    if bad:
        raise SetupError(f"the {what} {text!r} holds characters the launchers cannot carry: {' '.join(map(repr, bad))}")
    if not resolved.is_absolute():
        raise SetupError(f"the {what} must be an absolute path: {text!r}")
    return resolved


def check_port(value: object) -> int:
    try:
        port = int(str(value).strip())
    except ValueError as exc:
        raise SetupError(f"the port is not a number: {value!r}") from exc
    if not 1024 <= port <= 65535:
        raise SetupError(f"the port must be between 1024 and 65535: {port}")
    return port


def owned_env(answers: Answers) -> dict[str, str]:
    layout = answers.layout
    temp = str(layout.temp)
    return {
        "PORT": str(answers.port),
        "AGENT_CLI_BRIDGE_HOME": str(layout.data),
        "AGENT_CLI_BRIDGE_CONFIG_LOCAL": str(answers.settings_dir),
        "AGENT_CLI_BRIDGE_SHIM_DIR": str(layout.shim_dir),
        "BRIDGE_WORKDIR": str(layout.work),
        "TMPDIR": temp,
        "TMP": temp,
        "TEMP": temp,
    }


def gateway_env_text(answers: Answers, previous: str = "") -> str:
    """``gateway.env``: the owner's own lines kept, the wizard's keys rewritten at the end."""
    kept = [line for line in previous.splitlines() if _owned_key(line) is None]
    while kept and kept[-1].strip() in ("", "# Written by the AgentCliBridge setup; lines below are rewritten."):
        kept.pop()
    lines = [*kept, ""] if kept else []
    lines.append("# Written by the AgentCliBridge setup; lines below are rewritten.")
    lines += [f"{key}={value}" for key, value in owned_env(answers).items()]
    return "\n".join(lines) + "\n"


def _owned_key(line: str) -> str | None:
    match = _ENV_KEY.match(line)
    return match.group(1) if match and match.group(1) in OWNED_ENV_KEYS else None


def write_text_atomic(path: Path, text: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_record(layout: Layout) -> dict[str, object] | None:
    """``install.json`` as a dict, ``None`` when absent; ``SetupError`` when unreadable."""
    try:
        if not layout.record.is_file():
            return None
        data = json.loads(layout.record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError(f"cannot read {layout.record}: {exc}") from exc
    if not isinstance(data, dict) or data.get("app") != APP or data.get("format") != RECORD_FORMAT:
        raise SetupError(f"{layout.record} is not an AgentCliBridge install record")
    return data


def answers_from_record(layout: Layout, record: dict[str, object]) -> Answers:
    settings = record.get("settings_dir")
    return Answers(
        root=layout.root,
        settings_dir=Path(settings) if isinstance(settings, str) and settings else layout.default_settings,
        port=check_port(record.get("port", DEFAULT_PORT)),
        autostart=record.get("autostart") is True,
    )


def write_record(answers: Answers, manifest: Manifest) -> None:
    data = {
        "app": APP, "format": RECORD_FORMAT, "version": manifest.version, "commit": manifest.commit,
        "repo": manifest.repo, "settings_dir": str(answers.settings_dir), "port": answers.port,
        "autostart": answers.autostart,
    }
    write_text_atomic(answers.layout.record, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _posix_launchers(layout: Layout, python: Path) -> dict[str, str]:
    head = '#!/bin/sh\n# AgentCliBridge ({what}). Written by the setup; rewritten at each update.\n'
    here = 'here="$(cd "$(dirname "$0")" && pwd)"\n'
    gateway = here + f'{INSTALL_DIR_ENV}="$here" exec /bin/bash "$here/app/{{script}}"{{args}}\n'
    wizard = (
        here + f'PYTHONPATH="$here/app" PYTHONDONTWRITEBYTECODE=1 exec "{python}" -m bridge_installer'
        ' {flag} --dir "$here" "$@"\n'
    )
    return {
        "start.sh": head.format(what="start the gateway in the background") + gateway.format(script="install.sh", args=" --start"),
        "stop.sh": head.format(what="stop the gateway") + gateway.format(script="stop.sh", args=""),
        "kill.sh": head.format(what="force-stop the gateway") + gateway.format(script="kill.sh", args=""),
        "update.sh": head.format(what="update from the latest GitHub release") + wizard.format(flag="--update"),
        "uninstall.sh": head.format(what="remove this install") + wizard.format(flag="--uninstall"),
    }


def _windows_launchers(layout: Layout, python: Path) -> dict[str, str]:
    powershell = r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
    head = (
        "@echo off\r\nrem AgentCliBridge ({what}). Written by the setup; rewritten at each update.\r\n"
        'set "HERE=%~dp0"\r\nset "HERE=%HERE:~0,-1%"\r\n'
    )
    gateway = (
        f'set "{INSTALL_DIR_ENV}=%HERE%"\r\n'
        f'"{powershell}" -NoProfile -ExecutionPolicy Bypass -File "%HERE%\\app\\{{script}}"{{args}}\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    wizard = (
        'set "PYTHONPATH=%HERE%\\app"\r\nset "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f'"{python}" -m bridge_installer {{flag}} --dir "%HERE%" %*\r\nexit /b %ERRORLEVEL%\r\n'
    )
    return {
        "start.cmd": head.format(what="start the gateway in the background") + gateway.format(script="install.ps1", args=" -Start"),
        "stop.cmd": head.format(what="stop the gateway") + gateway.format(script="stop.ps1", args=""),
        "kill.cmd": head.format(what="force-stop the gateway") + gateway.format(script="kill.ps1", args=""),
        "update.cmd": head.format(what="update from the latest GitHub release") + wizard.format(flag="--update"),
        "uninstall.cmd": head.format(what="remove this install") + wizard.format(flag="--uninstall"),
    }


def write_launchers(layout: Layout, python: Path, *, is_windows: bool | None = None) -> list[Path]:
    """The launchers of this OS at the install root; ``python`` runs update and uninstall."""
    windows = sys.platform == "win32" if is_windows is None else is_windows
    scripts = _windows_launchers(layout, python) if windows else _posix_launchers(layout, python)
    written = []
    for name, text in scripts.items():
        target = layout.root / name
        write_text_atomic(target, text, mode=0o755)
        written.append(target)
    return written
