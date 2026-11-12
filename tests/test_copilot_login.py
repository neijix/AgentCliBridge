"""Copilot CLI's sign-in: ``copilot login --device-code`` hands back GitHub's device page and the
code to type; with no status or logout command, the host reads its config (or the GitHub CLI's
login it falls back on) and never pretends to sign it out."""

import io
import subprocess

import pytest

from agent_cli_bridge import cli_login
from agent_cli_bridge.cli_login import CliLogins, copilot_signed_in

DEVICE_PAGE = "https://github.com/login/device"
NO_GH = {"PATH": ""}


class _FakeLogin:
    """A stand-in ``copilot login`` process: prints its lines, then ends with ``code``."""

    def __init__(self, lines, code=None):
        self.stdout = io.StringIO("".join(lines))
        self.stdin = None
        self.returncode = code

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


def _config(tmp_path, body):
    folder = tmp_path / ".copilot"
    folder.mkdir()
    (folder / "config.json").write_text(
        "// User settings belong in settings.json.\n// This file is managed automatically.\n" + body,
        encoding="utf-8",
    )
    return str(tmp_path)


def _no_gh(monkeypatch):
    monkeypatch.setattr(cli_login.shutil, "which", lambda *_a, **_k: None)


def test_copilot_is_signed_in_by_its_config_users(tmp_path, monkeypatch):
    _no_gh(monkeypatch)
    home = _config(tmp_path, '{"logged_in_users": [{"host": "https://github.com", "login": "owner"}]}')
    assert copilot_signed_in(home, NO_GH) is True


def test_copilot_without_users_or_config_is_signed_out(tmp_path, monkeypatch):
    _no_gh(monkeypatch)
    assert copilot_signed_in(str(tmp_path), NO_GH) is False  # never launched
    home = _config(tmp_path, '{\n  "firstLaunchAt": "2026-10-07T22:02:10.514Z"\n}')
    assert copilot_signed_in(home, NO_GH) is False


def test_an_unreadable_copilot_config_is_unknown(tmp_path, monkeypatch):
    _no_gh(monkeypatch)
    assert copilot_signed_in(_config(tmp_path, "{not json"), NO_GH) is None


def test_a_token_in_the_environment_signs_copilot_in(tmp_path, monkeypatch):
    _no_gh(monkeypatch)
    assert copilot_signed_in(str(tmp_path), {"GH_TOKEN": "x"}) is True
    assert copilot_signed_in(str(tmp_path), {"COPILOT_GITHUB_TOKEN": "x"}) is True


def test_the_github_cli_login_signs_copilot_in(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_login.shutil, "which", lambda name, path=None: "/usr/bin/gh" if name == "gh" else None)
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="Logged in to github.com account owner")

    assert copilot_signed_in(str(tmp_path), NO_GH, run=run) is True
    # `gh auth status` answers by exit code; `gh auth token` would print the token.
    assert calls == [["/usr/bin/gh", "auth", "status", "--hostname", "github.com"]]

    def signed_out(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not logged in")

    assert copilot_signed_in(str(tmp_path), NO_GH, run=signed_out) is False


def test_copilot_device_login_returns_github_s_page_and_the_code(monkeypatch):
    monkeypatch.setattr(cli_login, "_drop_download_quarantine", lambda _binary: None)
    monkeypatch.setitem(cli_login.LOGIN_SPECS, "copilot", _spec_reading(False))
    started_argv = []

    def popen(argv, **kwargs):
        started_argv.append((argv, kwargs["env"].get("NO_OPEN_BROWSER")))
        return _FakeLogin([
            f"To authenticate, visit {DEVICE_PAGE} and enter code 92EC-55BB\n",
            "Waiting for authorization...\n",
        ])

    logins = CliLogins(popen=popen, link_wait=1.0)
    started = logins.start("copilot", "copilot")
    assert started_argv == [(["copilot", "login", "--device-code"], "1")]
    assert started["url"] == DEVICE_PAGE
    assert started["user_code"] == "92EC-55BB"
    assert started["needs_code"] is False
    status = logins.status("copilot", "copilot")
    assert status["signed_in"] is False and status["running"] is True and status["user_code"] == "92EC-55BB"


def test_a_cleanly_ended_copilot_login_counts_as_signed_in(monkeypatch):
    monkeypatch.setattr(cli_login, "_drop_download_quarantine", lambda _binary: None)
    monkeypatch.setitem(cli_login.LOGIN_SPECS, "copilot", _spec_reading(False))
    process = _FakeLogin([f"visit {DEVICE_PAGE} and enter code 92EC-55BB\n"])
    logins = CliLogins(popen=lambda *_a, **_k: process, link_wait=1.0)
    logins.start("copilot", "copilot")
    process.returncode = 0
    assert logins.status("copilot", "copilot")["signed_in"] is True
    process.returncode = 1  # a failed login is not trusted
    assert logins.status("copilot", "copilot")["signed_in"] is False


def test_copilot_cannot_be_signed_out_from_the_page(monkeypatch):
    def never_run(*_args, **_kwargs):
        raise AssertionError("no logout command may run")

    logins = CliLogins(run=never_run)
    with pytest.raises(ValueError, match="/logout"):
        logins.logout("copilot", "copilot")


def _spec_reading(value):
    from dataclasses import replace

    return replace(cli_login.LOGIN_SPECS["copilot"], read_status=lambda: value)
