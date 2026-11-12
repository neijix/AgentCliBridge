"""Start and stop an install's gateway, wait for its port, and the optional start at login.

The gateway runs through the snapshot's own launchers (``app/install.sh --start``, ``app/stop.sh``,
or their PowerShell twins) with ``AGENT_CLI_BRIDGE_INSTALL_DIR`` set, so a packaged install and a
checkout share one start path. The start at login is the only thing the setup writes outside the
install folder: a systemd user unit (Linux), a LaunchAgent (macOS), or an HKCU Run value (Windows).
"""
from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from bridge_installer import INSTALL_DIR_ENV
from bridge_installer.layout import Layout, SetupError

POWERSHELL = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
BASH = Path("/bin/bash")
SYSTEMCTL = Path("/usr/bin/systemctl") if Path("/usr/bin/systemctl").exists() else Path("/bin/systemctl")
LAUNCHCTL = Path("/bin/launchctl")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_command(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, check=False, **kwargs)  # type: ignore[call-overload]


def platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def install_id(root: Path) -> str:
    """A short id from the install folder, so two installs never share a unit or a Run value."""
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:10]


def gateway_env(layout: Layout) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("UV_") and key != "VIRTUAL_ENV"}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env[INSTALL_DIR_ENV] = str(layout.root)
    return env


def gateway_script(layout: Layout, action: str) -> list[str]:
    """The argv that starts (in the background), stops or force-stops this install's gateway."""
    if platform_name() == "windows":
        script, args = {"start": ("install.ps1", ["-Start"]), "stop": ("stop.ps1", []), "kill": ("kill.ps1", [])}[action]
        return [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(layout.app / script), *args]
    script, args = {"start": ("install.sh", ["--start"]), "stop": ("stop.sh", []), "kill": ("kill.sh", [])}[action]
    return [str(BASH), str(layout.app / script), *args]


def run_gateway_script(layout: Layout, action: str, *, runner: Runner = run_command) -> bool:
    if not layout.app.is_dir():
        return False
    done = runner(gateway_script(layout, action), cwd=str(layout.app), env=gateway_env(layout))
    return done.returncode == 0


def port_answers(port: int, *, timeout: float = 2.0) -> bool:
    """True when anything answers HTTP on 127.0.0.1:``port`` (an error status still answers)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout):  # noqa: S310 - fixed loopback URL
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):
        return False


def wait_for_port(port: int, *, seconds: float = 30.0, is_up: Callable[[int], bool] = port_answers) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if is_up(port):
            return True
        time.sleep(0.5)
    return False


# --- start at login -------------------------------------------------------------------------------

def systemd_unit_path(root: Path, home: Path | None = None) -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or (home or Path.home()) / ".config")
    return config / "systemd" / "user" / f"agentclibridge-{install_id(root)}.service"


def systemd_unit_text(layout: Layout) -> str:
    return (
        "[Unit]\n"
        f"Description=AgentCliBridge gateway ({layout.root})\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f'Environment="{INSTALL_DIR_ENV}={layout.root}"\n'
        f"WorkingDirectory={layout.app}\n"  # taken verbatim: systemd does not unquote this key
        f'ExecStart={BASH} "{layout.app / "start.sh"}"\n'
        "Restart=on-failure\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def launch_agent_label(root: Path) -> str:
    return f"com.agentclibridge.gateway.{install_id(root)}"


def launch_agent_path(root: Path, home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{launch_agent_label(root)}.plist"


def launch_agent_bytes(layout: Layout) -> bytes:
    log = str(layout.logs / "gateway.log")
    return plistlib.dumps({
        "Label": launch_agent_label(layout.root),
        "ProgramArguments": [str(BASH), str(layout.app / "start.sh")],
        "EnvironmentVariables": {INSTALL_DIR_ENV: str(layout.root)},
        "WorkingDirectory": str(layout.app),
        "RunAtLoad": True,
        "ProcessType": "Interactive",  # a Background agent is throttled: the gateway stalls
        "StandardOutPath": log,
        "StandardErrorPath": log,
    })


def run_value_name(root: Path) -> str:
    return f"AgentCliBridge-{install_id(root)}"


def run_value_command(layout: Layout) -> str:
    def quoted(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    command = f"$env:{INSTALL_DIR_ENV}={quoted(layout.root)}; & {quoted(layout.app / 'install.ps1')} -Start"
    return f'"{POWERSHELL}" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "{command}"'


def autostart_target(layout: Layout) -> str:
    """What the start at login writes outside the install folder, in words, for the wizard to show."""
    name = platform_name()
    if name == "windows":
        return f"the registry value HKCU\\{RUN_KEY}\\{run_value_name(layout.root)}"
    if name == "macos":
        return f"the LaunchAgent {launch_agent_path(layout.root)}"
    return f"the systemd user unit {systemd_unit_path(layout.root)}"


def has_systemd_user(runner: Runner = run_command) -> bool:
    if not SYSTEMCTL.exists():
        return False
    done = runner([str(SYSTEMCTL), "--user", "show-environment"], capture_output=True)
    return done.returncode == 0


def enable_autostart(layout: Layout, *, runner: Runner = run_command) -> None:
    """Write the start-at-login entry and start the gateway through it."""
    name = platform_name()
    if name == "linux":
        if not has_systemd_user(runner):
            raise SetupError("no systemd user manager answers here: run without --autostart and start it yourself")
        unit = systemd_unit_path(layout.root)
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(systemd_unit_text(layout), encoding="utf-8")
        runner([str(SYSTEMCTL), "--user", "daemon-reload"])
        done = runner([str(SYSTEMCTL), "--user", "enable", "--now", unit.name])
        if done.returncode != 0:
            raise SetupError(f"systemctl --user enable --now {unit.name} failed")
    elif name == "macos":
        plist = launch_agent_path(layout.root)
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(launch_agent_bytes(layout))
        domain = f"gui/{os.getuid()}"  # type: ignore[attr-defined,unused-ignore]
        runner([str(LAUNCHCTL), "bootout", f"{domain}/{launch_agent_label(layout.root)}"], capture_output=True)
        done = runner([str(LAUNCHCTL), "bootstrap", domain, str(plist)])
        if done.returncode != 0:
            raise SetupError(f"launchctl bootstrap {plist} failed")
    else:
        _set_run_value(run_value_name(layout.root), run_value_command(layout))
        run_gateway_script(layout, "start", runner=runner)


def stop_autostarted(layout: Layout, *, runner: Runner = run_command) -> None:
    """Stop the gateway a start-at-login entry keeps running (the entry stays)."""
    name = platform_name()
    if name == "linux" and systemd_unit_path(layout.root).exists():
        runner([str(SYSTEMCTL), "--user", "stop", systemd_unit_path(layout.root).name], capture_output=True)
    elif name == "macos" and launch_agent_path(layout.root).exists():
        label = launch_agent_label(layout.root)
        runner([str(LAUNCHCTL), "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)  # type: ignore[attr-defined,unused-ignore]


def disable_autostart(layout: Layout, *, runner: Runner = run_command) -> None:
    """Remove the start-at-login entry, if any (the gateway is stopped first)."""
    stop_autostarted(layout, runner=runner)
    name = platform_name()
    if name == "linux":
        unit = systemd_unit_path(layout.root)
        if unit.exists():
            runner([str(SYSTEMCTL), "--user", "disable", unit.name], capture_output=True)
            unit.unlink(missing_ok=True)
            runner([str(SYSTEMCTL), "--user", "daemon-reload"], capture_output=True)
    elif name == "macos":
        launch_agent_path(layout.root).unlink(missing_ok=True)
    else:
        _delete_run_value(run_value_name(layout.root))


def _set_run_value(name: str, command: str) -> None:
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)


def _delete_run_value(name: str) -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def remove_tree(path: Path) -> bool:
    """Delete ``path`` (a folder or a file); False when something in it could not be removed."""
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except OSError:
            return False
        return True
    if not path.exists():
        return True
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()
