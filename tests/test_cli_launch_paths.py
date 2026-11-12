"""CLI launches by full path: the version probe and the status run the binary discovery found,
and the Windows update and uninstall plans carry winget's and npm's full paths."""

import json
import subprocess

from agent_cli_bridge.cli_status import CliStatus, uninstall_plan, update_plan
from agent_cli_bridge.cli_tools import windows_tool


def test_the_version_probe_runs_and_clears_the_path_discovery_found_not_another_one_on_path(monkeypatch):
    from agent_cli_bridge import cli_status

    events: list[str] = []
    monkeypatch.setattr(cli_status.shutil, "which", lambda command: f"/elsewhere/{command}")
    monkeypatch.setattr(cli_status, "clear_macos_quarantine", lambda path: events.append(f"clear:{path}") or False)

    def run(argv, **kwargs):
        events.append(f"run:{argv[0]}")
        return subprocess.CompletedProcess(argv, 0, stdout="2.1.280 (Claude Code)", stderr="")

    monkeypatch.setattr(cli_status.subprocess, "run", run)
    assert "2.1.280" in cli_status.run_version("claude", path="/found/claude")
    assert events == ["clear:/found/claude", "run:/found/claude"]


def test_the_status_probes_the_binary_discovery_found(monkeypatch):
    from agent_cli_bridge import cli_status

    launched: list[str] = []
    monkeypatch.setattr(cli_status.shutil, "which", lambda command: f"/elsewhere/{command}")
    monkeypatch.setattr(cli_status, "clear_macos_quarantine", lambda path: False)

    def run(argv, **kwargs):
        launched.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="2.1.280", stderr="")

    monkeypatch.setattr(cli_status.subprocess, "run", run)
    status = CliStatus(fetch=lambda url: json.dumps({"latest": "2.1.280"}).encode(), clock=lambda: 1.0)
    status.status([{"command": "claude", "name": "Claude Code", "path": "/found/claude"}])
    assert launched == ["/found/claude"]
    status.forget("claude")  # a re-read after an update (no path given) keeps the same binary
    status.installed("claude")
    assert launched == ["/found/claude", "/found/claude"]


def test_windows_helpers_are_found_by_full_path(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    winget = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe"
    npm = r"C:\Program Files\nodejs\npm.cmd"
    assert windows_tool("winget", which=lambda name: winget) == winget
    seen: list[list[str]] = []

    def find(paths):
        seen.append(paths)
        return npm

    assert windows_tool("npm.cmd", which=lambda name: None, find=find) == npm
    assert r"C:\Program Files\nodejs\npm.cmd" in seen[0]
    assert r"C:\Users\me\AppData\Roaming\npm\npm.cmd" in seen[0]
    # Nothing found: the bare name, so the run fails with a clear "could not start".
    assert windows_tool("winget", which=lambda name: None, find=lambda paths: "") == "winget"


def test_windows_update_and_uninstall_plans_carry_the_full_path_of_winget_and_npm():
    winget = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe"
    npm = r"C:\Program Files\nodejs\npm.cmd"
    tool = {"winget": winget, "npm.cmd": npm}.__getitem__
    shim = r"C:\Users\me\AppData\Roaming\npm\copilot.cmd"
    package = (
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages"
        r"\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\copilot.exe"
    )
    assert update_plan("copilot", shim, shim, is_windows=True, tool=tool)["argv"][0] == npm
    assert update_plan("copilot", package, package, is_windows=True, tool=tool)["argv"][0] == winget
    assert uninstall_plan("copilot", shim, shim, is_windows=True, tool=tool)["argv"][0] == npm
    assert uninstall_plan("copilot", package, package, is_windows=True, tool=tool)["argv"][0] == winget
