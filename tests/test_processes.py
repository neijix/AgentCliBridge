"""Background probes — a version check, an update, a model listing — never open a console
window when the host runs under pythonw on Windows, and POSIX callers see none of it."""

import subprocess
from types import SimpleNamespace

import pytest

from agent_cli_bridge import cli_status, model_catalog, processes

CREATE_NO_WINDOW = 0x08000000


def _simulate_os(monkeypatch, is_windows: bool) -> None:
    monkeypatch.setattr(processes, "os", SimpleNamespace(name="nt" if is_windows else "posix"))
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW, raising=False)
    # xattr only exists on macOS; the probes below must not depend on it.
    monkeypatch.setattr(cli_status, "clear_macos_quarantine", lambda path: False)
    monkeypatch.setattr(model_catalog, "clear_macos_quarantine", lambda path: False)


@pytest.mark.parametrize("is_windows", [False, True])
def test_background_options_are_windows_only(monkeypatch, is_windows):
    _simulate_os(monkeypatch, is_windows)
    expected = {"creationflags": CREATE_NO_WINDOW} if is_windows else {}
    assert processes.background_process_options() == expected


def test_named_platform_picks_the_hidden_console_flag(monkeypatch):
    """A caller names the platform, so the runner does not keep a second copy of the flag."""
    _simulate_os(monkeypatch, False)
    assert processes.background_process_options("nt") == {"creationflags": CREATE_NO_WINDOW}
    assert processes.background_process_options("posix") == {}


def test_version_and_update_processes_do_not_open_a_console(monkeypatch):
    _simulate_os(monkeypatch, True)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "1.2.3", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert "1.2.3" in cli_status.run_version("claude")
    assert cli_status.run_update(["claude", "update"]) == (0, "1.2.3")
    assert len(calls) == 2
    for _, options in calls:
        assert options["creationflags"] == CREATE_NO_WINDOW
        assert options["stdin"] == subprocess.DEVNULL
        assert not options.get("shell")


@pytest.mark.parametrize("is_windows", [False, True])
def test_a_model_listing_carries_the_background_options(monkeypatch, is_windows):
    _simulate_os(monkeypatch, is_windows)
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "grok-4.7\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert "grok-4.7" in model_catalog.run_list(["grok", "models"])
    assert len(calls) == 1
    if is_windows:
        assert calls[0]["creationflags"] == CREATE_NO_WINDOW
    else:
        assert "creationflags" not in calls[0]
