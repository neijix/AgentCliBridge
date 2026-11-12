"""Signing an agent CLI in: the host runs the CLI's own browser login, hands back only a link
on that CLI's host, and reports whether the CLI is signed in now."""

import os
import stat
import subprocess
import sys
import time

import pytest

from agent_cli_bridge import cli_login
from agent_cli_bridge.cli_login import (
    CODE_MAX,
    CliLogins,
    _tail,
    can_sign_in,
    login_link,
    login_user_code,
    parse_signed_in,
    sign_in_needs_code,
)
from agent_cli_bridge.host import AgentHost

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake CLI is a shell script")

LINK = "https://cursor.com/loginDeepControl?challenge=abc&uuid=1&mode=login&redirectTarget=cli"
CLAUDE_LINK = (
    "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    "&response_type=code&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
)
GROK_LINK = "https://auth.x.ai/activate?user_code=WDRA-TKXP"
OPENROUTER_PAGE = "https://openrouter.ai/keys"
COPILOT_PAGE = "https://github.com/login/device"


def _fake_cursor(tmp_path, *, link=LINK, signed_in_marker=None):
    """A stand-in ``cursor-agent``: ``login`` prints the link and waits; ``status`` answers."""
    marker = signed_in_marker or tmp_path / "signed-in"
    script = tmp_path / "cursor-agent"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = login ]; then\n'
        '  echo "Starting login process..."\n'
        '  echo "browser=$NO_OPEN_BROWSER"\n'
        f'  echo "Open a browser and navigate to this link: {link}"\n'
        "  sleep 30\n"
        'elif [ "$1" = logout ]; then\n'
        f'  rm -f "{marker}"\n'
        '  echo "Logged out"\n'
        "else\n"
        f'  if [ -f "{marker}" ]; then echo "Logged in as owner@example.com"; else echo "Not logged in"; fi\n'
        "fi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), marker


def _fake_claude(tmp_path, *, link=CLAUDE_LINK, signed_in_marker=None):
    """A stand-in ``claude``: ``auth login`` prints the link and waits for a pasted code."""
    marker = signed_in_marker or tmp_path / "claude-signed-in"
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = auth ] && [ "$2" = login ]; then\n'
        '  echo "Opening browser to sign in…"\n'
        '  echo "browser=$BROWSER"\n'
        f'  echo "If the browser didn\'t open, visit: {link}"\n'
        '  echo "Paste code here if prompted > "\n'
        "  read code\n"
        "  read extra\n"
        '  if [ "$code" = GOODCODE ]; then\n'
        f'    touch "{marker}"\n'
        '    echo "Login successful"\n'
        "  fi\n"
        'elif [ "$1" = auth ] && [ "$2" = status ]; then\n'
        f'  if [ -f "{marker}" ]; then echo \'{{"loggedIn": true}}\'; else echo \'{{"loggedIn": false}}\'; fi\n'
        "fi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), marker


def _fake_grok(tmp_path, *, link=GROK_LINK, signed_in_marker=None):
    """A stand-in ``grok``: ``login --device-auth`` prints the URL + code; ``models`` answers."""
    marker = signed_in_marker or tmp_path / "grok-signed-in"
    script = tmp_path / "grok"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = login ]; then\n'
        '  echo "To sign in, open this URL in your browser:"\n'
        f'  echo "{link}"\n'
        '  echo "Make sure your browser shows this code: WDRA-TKXP"\n'
        "  sleep 30\n"
        'elif [ "$1" = logout ]; then\n'
        f'  rm -f "{marker}"\n'
        '  echo "Logged out"\n'
        'elif [ "$1" = models ]; then\n'
        f'  if [ -f "{marker}" ]; then echo "You are logged in with grok.com."; '
        'else echo "You are not authenticated."; fi\n'
        "fi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), marker


def _fake_opencode(tmp_path, *, signed_in_marker=None):
    """A stand-in ``opencode``: ``auth login`` waits for a pasted key; ``auth list`` answers."""
    marker = signed_in_marker or tmp_path / "opencode-signed-in"
    script = tmp_path / "opencode"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = auth ] && [ "$2" = login ]; then\n'
        '  echo "Enter your API key"\n'
        "  read key\n"
        "  read extra\n"
        '  echo "got $key"\n'
        '  if [ -n "$key" ]; then\n'
        f'    touch "{marker}"\n'
        '    echo "Done"\n'
        "  fi\n"
        'elif [ "$1" = auth ] && [ "$2" = logout ]; then\n'
        f'  rm -f "{marker}"\n'
        '  echo "Logged out"\n'
        'elif [ "$1" = auth ] && [ "$2" = list ]; then\n'
        f'  if [ -f "{marker}" ]; then echo "OpenRouter api"; echo "1 credentials"; '
        'else echo "0 credentials"; fi\n'
        "fi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), marker


def test_only_a_link_on_the_cli_s_own_host_is_handed_to_the_browser():
    hosts = ("cursor.com",)
    assert login_link(f"navigate to this link: {LINK}", hosts) == LINK
    assert login_link("go to https://evil.example/cursor.com/login", hosts) == ""
    assert login_link("go to http://cursor.com/login", hosts) == ""  # never plain http
    assert login_link("go to https://cursor.com.evil.example/login", hosts) == ""
    assert login_link(f"visit: {CLAUDE_LINK}", ("claude.com",)) == CLAUDE_LINK
    assert login_link(f"visit: {CLAUDE_LINK}", ("cursor.com",)) == ""
    assert login_link(f"open {GROK_LINK}", ("auth.x.ai",)) == GROK_LINK
    assert login_link(OPENROUTER_PAGE, ("openrouter.ai",)) == OPENROUTER_PAGE
    assert login_user_code(GROK_LINK) == "WDRA-TKXP"
    assert login_user_code("Make sure your browser shows this code: ABCD-1234") == "ABCD-1234"
    assert login_user_code("no code here") == ""
    # Copilot: no separator, so only a dashed code counts ("enter code here" is no code).
    assert login_user_code(f"To authenticate, visit {COPILOT_PAGE} and enter code 92EC-55BB") == "92EC-55BB"
    assert login_user_code("enter code here") == ""
    assert login_link(f"visit {COPILOT_PAGE} and enter", ("github.com",)) == COPILOT_PAGE
    assert login_link("visit https://github.com.evil.example/login/device", ("github.com",)) == ""


def test_status_output_reads_as_signed_in_signed_out_or_unknown():
    assert parse_signed_in(0, "Not logged in") is False
    assert parse_signed_in(1, "Error: Authentication required. Please run 'agent login'") is False
    assert parse_signed_in(0, "✓ Logged in as owner@example.com") is True
    assert parse_signed_in(0, "something else") is None
    assert parse_signed_in(1, '{"loggedIn": false, "authMethod": "none"}') is False
    assert parse_signed_in(0, '{"loggedIn": true, "authMethod": "claude.ai"}') is True
    assert parse_signed_in(0, "You are logged in with grok.com.") is True
    assert parse_signed_in(0, "You are not authenticated.") is False
    assert parse_signed_in(0, "OpenRouter api\n1 credentials") is True
    assert parse_signed_in(0, "0 credentials") is False
    # OpenCode names OpenRouter even with no key; 0 credentials must win.
    assert parse_signed_in(0, "OpenRouter api\n0 credentials") is False
    assert (
        parse_signed_in(
            0,
            "●  OpenRouter \x1b[90mapi\n└  1 credentials\n\x1b[0m\n",
        )
        is True
    )


def test_an_openrouter_mention_that_is_not_a_credential_is_not_a_sign_in():
    assert parse_signed_in(0, "Error: no OpenRouter key found") is None
    assert parse_signed_in(0, "Add credential for openrouter? (y/N)") is None
    assert parse_signed_in(0, "OpenRouter api key is invalid") is None
    assert parse_signed_in(0, "┌  Credentials\n│\n●  OpenRouter oauth\n│\n└  1 credentials") is True


def test_only_known_clis_can_be_signed_in():
    assert can_sign_in("agent") and can_sign_in("cursor-agent") and can_sign_in("claude")
    assert can_sign_in("grok") and can_sign_in("opencode")
    assert not can_sign_in("gemini") and not can_sign_in("agy")
    assert sign_in_needs_code("claude") is True
    assert sign_in_needs_code("opencode") is True
    assert sign_in_needs_code("cursor-agent") is False
    assert sign_in_needs_code("grok") is False
    assert sign_in_needs_code("gemini") is False
    assert can_sign_in("copilot") and sign_in_needs_code("copilot") is False
    with pytest.raises(ValueError, match="cannot sign"):
        CliLogins().start("rm", "/bin/rm")


def test_login_runs_without_a_browser_returns_its_link_and_reports_the_sign_in(tmp_path):
    binary, marker = _fake_cursor(tmp_path)
    logins = CliLogins()
    started = logins.start("cursor-agent", binary)
    assert started["url"] == LINK
    assert started["running"] is True
    assert "browser=1" in started["output"]  # NO_OPEN_BROWSER: the node never opens a browser itself
    # Asking again reuses the login still waiting instead of starting a second one.
    assert logins.start("cursor-agent", binary)["url"] == LINK

    status = logins.status("cursor-agent", binary)
    assert status["signed_in"] is False and status["running"] is True and status["url"] == LINK
    marker.write_text("")
    assert logins.status("cursor-agent", binary)["signed_in"] is True
    logins._stop("cursor-agent")


def test_claude_login_returns_its_link_and_finishes_when_the_code_is_pasted(tmp_path):
    binary, marker = _fake_claude(tmp_path)
    logins = CliLogins()
    started = logins.start("claude", binary)
    assert started["url"] == CLAUDE_LINK
    assert started["running"] is True and started["needs_code"] is True
    assert "browser=true" in started["output"]
    status = logins.status("claude", binary)
    assert status["signed_in"] is False and status["needs_code"] is True
    with pytest.raises(ValueError, match="does not take a pasted code"):
        logins.submit("cursor-agent", "GOODCODE")
    with pytest.raises(ValueError, match="Paste the code"):
        logins.submit("claude", "")
    logins.submit("claude", "GOODCODE")
    for _ in range(20):
        if marker.exists():
            break
        time.sleep(0.05)
    assert logins.status("claude", binary)["signed_in"] is True
    logins._stop("claude")


def test_grok_device_auth_returns_its_link_and_the_code_to_type(tmp_path):
    binary, marker = _fake_grok(tmp_path)
    logins = CliLogins()
    started = logins.start("grok", binary)
    assert started["url"] == GROK_LINK
    assert started["running"] is True and started["needs_code"] is False
    assert started["user_code"] == "WDRA-TKXP"
    status = logins.status("grok", binary)
    assert status["signed_in"] is False and status["user_code"] == "WDRA-TKXP"
    marker.write_text("")
    assert logins.status("grok", binary)["signed_in"] is True
    logins.logout("grok", binary)
    assert logins.status("grok", binary)["signed_in"] is False
    assert not marker.exists()


def test_output_redacts_bearer_and_api_key_shapes():
    """Shown CLI output drops bearer tokens and API keys, including keys that do not start with sk-."""
    sk = "sk-proj12345678"
    openrouter = "sk-or-v1-deadbeefcafebabe"
    bearer = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N"
    )
    labeled = "plainkeyvalue123456"
    spaced = "spacedsecretvalue99"
    header = "notsksecretvalue1"
    github = "ghp_" + ("b" * 36)
    fine = "github_pat_" + ("c" * 22)
    text = (
        f"before Authorization: Bearer {bearer} "
        f"api_key={labeled} API key: {spaced} x-api-key: {header} "
        f"{github} {fine} {sk} {openrouter} after WDRA-TKXP browser=1"
    )
    out = _tail(text)
    for secret in (sk, openrouter, bearer, "eyJzdWIiOiIxMjM0NTY3ODkwIn0", labeled, spaced, header, github, fine):
        assert secret not in out
    assert "[redacted]" in out
    assert "before" in out and "after" in out
    assert "WDRA-TKXP" in out and "browser=1" in out


def test_submit_rejects_empty_newline_and_overlong():
    """An empty paste, an internal newline, or a paste over CODE_MAX never reaches the CLI."""
    logins = CliLogins()
    for pasted in ("", " \t ", "has\ninside", "has\rinside", "x" * (CODE_MAX + 1)):
        with pytest.raises(ValueError, match="Paste the code"):
            logins.submit("claude", pasted)
    # At the limit the length check lets it through; nothing is waiting, so this is the later error.
    with pytest.raises(ValueError, match="No sign-in is waiting"):
        logins.submit("claude", "y" * CODE_MAX)


def test_opencode_sign_in_opens_the_keys_page_and_stores_a_pasted_key(tmp_path):
    binary, marker = _fake_opencode(tmp_path)
    logins = CliLogins(link_wait=0.2)
    started = logins.start("opencode", binary)
    assert started["url"] == OPENROUTER_PAGE
    assert started["running"] is True and started["needs_code"] is True
    with pytest.raises(ValueError, match="Paste the code"):
        logins.submit("opencode", "")
    logins.submit("opencode", "sk-or-v1-deadbeefcafebabe")
    for _ in range(20):
        if marker.exists():
            break
        time.sleep(0.05)
    status = logins.status("opencode", binary)
    assert status["signed_in"] is True
    assert "sk-or-v1-deadbeefcafebabe" not in status["output"]
    assert "[redacted]" in status["output"]
    logins.logout("opencode", binary)
    assert logins.status("opencode", binary)["signed_in"] is False
    assert not marker.exists()


def test_a_login_that_prints_a_foreign_link_is_refused_and_stopped(tmp_path):
    binary, _ = _fake_cursor(tmp_path, link="https://evil.example/login")
    logins = CliLogins(link_wait=3)
    with pytest.raises(ValueError, match="no sign-in link"):
        logins.start("cursor-agent", binary)
    login = logins._logins["cursor-agent"]
    login.process.wait(timeout=5)  # the waiting CLI was terminated, not left behind


def _host_with(tmp_path, agents):
    return AgentHost(
        known_models=tmp_path / "known.json",
        agents_provider=lambda: agents,
        home=tmp_path,
        env={},
    )


def test_the_host_signs_in_only_a_cli_it_found_never_the_grok_binary_named_agent(tmp_path):
    binary, _ = _fake_cursor(tmp_path)
    host = _host_with(
        tmp_path, [{"command": "cursor-agent", "name": "Cursor Agent", "binary_found": False, "path": ""}]
    )
    with pytest.raises(ValueError, match="No agent CLI"):
        host.sign_in("cursor-agent")
    grok = os.path.join(str(tmp_path), ".grok", "bin", "agent")
    host = _host_with(
        tmp_path, [{"command": "agent", "name": "Cursor Agent", "flavor": "cursor", "binary_found": True, "path": grok}]
    )
    with pytest.raises(ValueError, match="Grok"):
        host.sign_in("agent")
    host = _host_with(tmp_path, [{"command": "gemini", "name": "Gemini CLI", "binary_found": True, "path": binary}])
    with pytest.raises(ValueError, match="cannot sign"):
        host.sign_in("gemini")  # a found CLI with no browser login known here


def test_a_sign_in_clears_quarantine_before_the_cli_starts(tmp_path, monkeypatch):
    import subprocess

    binary, _marker = _fake_cursor(tmp_path)
    events: list[str] = []

    def popen(argv, **kwargs):
        events.append("popen")
        return subprocess.Popen(argv, **kwargs)

    monkeypatch.setattr(
        "agent_cli_bridge.cli_status.clear_macos_quarantine",
        lambda path: events.append(f"clear:{path}") or False,
    )
    logins = CliLogins(popen=popen)
    logins.start("cursor-agent", binary)
    assert events[0] == f"clear:{binary}"
    assert events.index("popen") > 0
    logins._stop("cursor-agent")


def test_xai_keys_are_redacted_from_shown_output():
    key = "xai-AbCdEf0123456789xyz"
    out = _tail(f"before {key} after XAI_KEY=xai-short")
    assert key not in out and "[redacted]" in out
    assert "before" in out and "after" in out and "xai-short" in out  # too short to be a key


class _Proc:
    """A login process that ignores ``terminate`` unless ``stubborn`` is False; records what it was told."""

    def __init__(self, *, stubborn):
        self.stdout = iter(())
        self.stdin = None
        self.returncode = None
        self.stubborn = stubborn
        self.calls: list[str] = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        if not self.stubborn:
            self.returncode = -15

    def kill(self):
        self.calls.append("kill")
        self.returncode = -9

    def wait(self, timeout=None):
        self.calls.append(f"wait:{timeout}")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("login", timeout)
        return self.returncode


def test_a_login_that_ignores_terminate_is_killed_and_collected(monkeypatch):
    monkeypatch.setattr(cli_login, "_drop_download_quarantine", lambda _binary: None)
    stubborn = _Proc(stubborn=True)
    logins = CliLogins(popen=lambda *a, **k: stubborn, link_wait=0.05)
    logins.start("opencode", "opencode")
    logins._stop("opencode")
    assert stubborn.calls[0] == "terminate" and "kill" in stubborn.calls
    assert stubborn.calls.index("kill") > stubborn.calls.index("terminate")
    assert stubborn.calls[-1].startswith("wait:") and stubborn.returncode == -9
    polite = _Proc(stubborn=False)
    logins = CliLogins(popen=lambda *a, **k: polite, link_wait=0.05)
    logins.start("opencode", "opencode")
    logins._stop("opencode")
    assert polite.calls == ["terminate", f"wait:{cli_login.STOP_GRACE}"]


def test_every_expired_login_is_swept_not_only_the_one_asked_about():
    now = [0.0]
    old, fresh = _Proc(stubborn=False), _Proc(stubborn=False)
    logins = CliLogins(clock=lambda: now[0])
    logins._logins["claude"] = cli_login._Login(process=old, started_at=0.0)
    logins._logins["opencode"] = cli_login._Login(process=fresh, started_at=cli_login.LOGIN_TIMEOUT - 1)
    now[0] = cli_login.LOGIN_TIMEOUT + 1
    logins.status("opencode", "/bin/true")  # asks about opencode; claude's expired login is ended too
    assert "terminate" in old.calls and not fresh.calls
    assert "claude" not in logins._logins and "opencode" in logins._logins
