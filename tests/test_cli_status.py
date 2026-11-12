"""CLI version checks: parsing ``--version`` outputs and release sources, the outdated verdict,
the cache, and AgentHost's update."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from agent_cli_bridge.cli_status import (
    CLAUDE_RELEASE_LATEST_URL,
    CURSOR_INSTALL_URL,
    FAILURE_TTL,
    HOMEBREW_FORMULA_API,
    INSTALLED_TTL,
    LATEST_TTL,
    ClaudeReleaseError,
    CliStatus,
    catch_up_claude_cask,
    claude_release_url,
    clear_macos_quarantine,
    homebrew_formula,
    install_plan,
    install_published_claude,
    is_claude_cask_binary,
    is_claude_latest_cask_binary,
    is_outdated,
    latest_url,
    parse_latest,
    parse_version,
    remove_native_install,
    uninstall_plan,
    update_plan,
)

AGENTS = [
    {"command": "claude", "name": "Claude Code"},
    {"command": "agent", "name": "Cursor Agent"},
    {"command": "agy", "name": "Google Antigravity"},
    {"command": "grok", "name": "Grok CLI"},
    {"command": "opencode", "name": "Open Router"},
]
VERSION_OUTPUT = {
    "claude": "2.1.267 (Claude Code)\n",
    "gemini": "0.60.0\n",
    "agent": "2026.09.18-9a7762b\n",
    "agy": "1.2.8\n",
    "copilot": "GitHub Copilot CLI 1.0.87.\n",
    "grok": "grok 1.0.40 (eb1a2256660d) [alpha]\n",
    "opencode": "1.18.30\n",
}
CURSOR_SCRIPT = b'#!/bin/bash\nDOWNLOAD_URL="https://downloads.cursor.com/lab/2026.09.18-9a7762b/${OS}/${ARCH}/agent-cli-package.tar.gz"\n'


class Fakes:
    """A fake ``--version`` runner and release-source fetcher that count their calls."""

    def __init__(self, *, latest=None, broken=()):
        self.latest = (
            latest
            if latest is not None
            else {
                "@anthropic-ai/claude-code": "2.1.280",
                "opencode-ai": "1.18.32",
                "@xai-official/grok": "1.0.40",
            }
        )
        self.broken = set(broken)
        self.runs = []
        self.fetches = []
        self.now = 1_000.0

    def run(self, command):
        self.runs.append(command)
        if command in self.broken:
            raise FileNotFoundError(f"{command}: not found")
        return VERSION_OUTPUT[command]

    def fetch(self, url):
        self.fetches.append(url)
        if url == CURSOR_INSTALL_URL:
            return CURSOR_SCRIPT
        for package, version in self.latest.items():
            if package.replace("/", "%2F") in url or package in url:
                return json.dumps({"stable": "0.0.1", "latest": version}).encode()
        raise OSError("registry down")

    def clock(self):
        return self.now


def test_version_outputs_of_every_cli_parse_to_a_bare_version():
    assert parse_version(VERSION_OUTPUT["claude"]) == "2.1.267"
    assert parse_version(VERSION_OUTPUT["copilot"]) == "1.0.87"
    assert parse_version(VERSION_OUTPUT["grok"]) == "1.0.40"
    assert parse_version(VERSION_OUTPUT["agent"]) == "2026.09.18-9a7762b"
    assert parse_version("nothing here") == ""


def test_newer_compares_numerically_and_unknown_is_neither():
    assert is_outdated("2.1.267", "2.1.280") is True
    assert is_outdated("2.1.9", "2.1.10") is True
    assert is_outdated("2.1.280", "2.1.280") is False
    assert is_outdated("2.1.281", "2.1.280") is False  # ahead of the channel (pre-release): fine
    assert is_outdated("2026.09.18-9a7762b", "2026.09.18-ffffff") is False
    assert is_outdated("", "2.1.280") is None
    assert is_outdated("2.1.280", "") is None


def test_release_sources_are_the_npm_dist_tags_or_cursors_install_script():
    assert latest_url("claude") == "https://registry.npmjs.org/-/package/@anthropic-ai%2Fclaude-code/dist-tags"
    assert latest_url("opencode") == "https://registry.npmjs.org/-/package/opencode-ai/dist-tags"
    assert latest_url("agent") == CURSOR_INSTALL_URL
    assert latest_url("agy") == ""  # `agy update` installs; there is no query-only check
    assert parse_latest("claude", b'{"stable":"2.1.267","latest":"2.1.280","next":"2.1.280"}') == "2.1.280"
    assert parse_latest("claude", b"not json") == ""
    assert parse_latest("claude", b'["latest"]') == ""
    assert parse_latest("agent", CURSOR_SCRIPT) == "2026.09.18-9a7762b"
    assert parse_latest("agent", b"#!/bin/bash\necho no build here\n") == ""


def test_status_rows_say_installed_latest_and_whether_behind():
    fakes = Fakes()
    status = CliStatus(run=fakes.run, fetch=fakes.fetch, clock=fakes.clock).status(AGENTS)
    assert status["checked_at"] == 1_000.0
    rows = {row["command"]: row for row in status["agents"]}
    assert rows["claude"] == {
        "command": "claude",
        "name": "Claude Code",
        "installed": "2.1.267",
        "latest": "2.1.280",
        "is_outdated": True,
        "source": "npm",
        "error": "",
        "can_sign_in": True,
        "needs_code": True,
    }
    assert rows["agent"]["can_sign_in"] is True  # Cursor signs in from Settings
    assert rows["agent"]["needs_code"] is False  # Cursor finishes in the browser, no pasted code
    assert rows["agent"]["installed"] == "2026.09.18-9a7762b"
    assert rows["agent"]["latest"] == "2026.09.18-9a7762b"
    assert rows["agent"]["is_outdated"] is False
    assert rows["agent"]["source"] == "cursor"
    assert rows["agy"] == {
        "command": "agy",
        "name": "Google Antigravity",
        "installed": "1.2.8",
        "latest": "",
        "is_outdated": None,
        "source": "",
        "error": "",
        "can_sign_in": False,
        "needs_code": False,
    }
    assert rows["grok"]["can_sign_in"] is True
    assert rows["grok"]["needs_code"] is False
    assert rows["opencode"]["can_sign_in"] is True
    assert rows["opencode"]["needs_code"] is True
    assert rows["opencode"]["is_outdated"] is True
    assert "agy" not in " ".join(fakes.fetches)  # nothing to ask for agy


def test_a_homebrew_formula_is_compared_with_what_homebrew_ships_not_npm(tmp_path):
    # npm has 1.18.32 but the formula still ships 1.18.30: `brew upgrade` could not deliver it,
    # so the row must not say "behind" (the Update button did nothing).
    binary = tmp_path / "Cellar" / "opencode" / "1.18.30_2" / "bin" / "opencode"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    link = tmp_path / "bin" / "opencode"
    link.parent.mkdir()
    link.symlink_to(binary)
    assert homebrew_formula(os.path.realpath(link)) == "opencode"
    assert homebrew_formula("/usr/local/lib/node_modules/opencode-ai/bin/opencode") == ""
    assert homebrew_formula("/opt/homebrew/Cellar/--evil/1/bin/x") == ""
    fetches = []

    def fetch(url):
        fetches.append(url)
        if url == f"{HOMEBREW_FORMULA_API}/opencode.json":
            return json.dumps({"name": "opencode", "versions": {"stable": shipped, "head": None}}).encode()
        return json.dumps({"latest": "1.18.32"}).encode()

    shipped = "1.18.30"
    status = CliStatus(run=Fakes().run, fetch=fetch, clock=lambda: 1.0)
    agents = [{"command": "opencode", "name": "Open Router", "path": str(link)}]
    row = status.status(agents)["agents"][0]
    assert row["latest"] == "1.18.30" and row["is_outdated"] is False and row["source"] == "homebrew"
    assert fetches == [f"{HOMEBREW_FORMULA_API}/opencode.json"]
    shipped = "1.18.32"
    row = status.status(agents, force=True)["agents"][0]
    assert row["latest"] == "1.18.32" and row["is_outdated"] is True
    assert parse_latest("opencode", b"not json", "opencode") == ""


@pytest.mark.parametrize("cask", ["claude-code@latest", "claude-code"])
def test_a_claude_cask_is_compared_with_anthropics_download_not_npm(tmp_path, cask):
    # npm said 2.1.292 while the cask and Anthropic's download were both at 2.1.291: the row
    # offered Update, and the update could only fail ("not a binary either of them is offering").
    binary = tmp_path / "Caskroom" / cask / "2.1.267" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    link = tmp_path / "bin" / "claude"
    link.parent.mkdir()
    link.symlink_to(binary)
    assert is_claude_cask_binary(os.path.realpath(link))
    assert not is_claude_cask_binary("/opt/homebrew/Caskroom/other/1/claude")
    assert not is_claude_cask_binary("")
    fetches = []

    def fetch(url):
        fetches.append(url)
        if url == CLAUDE_RELEASE_LATEST_URL:
            return f"{published}\n".encode()
        return json.dumps({"latest": "2.1.292"}).encode()

    published = "2.1.267"
    status = CliStatus(run=Fakes().run, fetch=fetch, clock=lambda: 1.0)
    agents = [{"command": "claude", "name": "Claude Code", "path": str(link)}]
    row = status.status(agents)["agents"][0]
    assert row["latest"] == "2.1.267" and row["is_outdated"] is False and row["source"] == "anthropic"
    assert fetches == [CLAUDE_RELEASE_LATEST_URL]
    published = "2.1.292"
    row = status.status(agents, force=True)["agents"][0]
    assert row["latest"] == "2.1.292" and row["is_outdated"] is True
    # The update's own npm read is cached apart from this one.
    assert status.latest("claude")["source"] == "npm"
    assert parse_latest("claude", b"<html>", is_claude_cask=True) == ""


def test_a_missing_binary_or_a_dead_registry_is_a_row_with_its_reason_never_an_error():
    fakes = Fakes(latest={}, broken={"claude"})
    status = CliStatus(run=fakes.run, fetch=fakes.fetch, clock=fakes.clock).status(AGENTS)
    rows = {row["command"]: row for row in status["agents"]}
    assert rows["claude"]["installed"] == ""
    assert rows["claude"]["is_outdated"] is None
    assert "not found" in rows["claude"]["error"]
    assert rows["opencode"]["installed"] == "1.18.30"
    assert rows["opencode"]["latest"] == ""
    assert rows["opencode"]["is_outdated"] is None
    assert rows["opencode"]["error"] == "registry down"


def test_a_stuck_cli_is_reported_not_waited_for_again():
    def hang(command):
        raise subprocess.TimeoutExpired(cmd=[command, "--version"], timeout=20)

    fakes = Fakes()
    status = CliStatus(run=hang, fetch=fakes.fetch, clock=fakes.clock)
    first = status.status(AGENTS[:1])["agents"][0]
    assert first["installed"] == ""
    assert "timed out" in first["error"]
    status.status(AGENTS[:1])
    assert fakes.fetches.count(latest_url("claude")) == 1  # the fetch side is cached too


def test_checks_are_cached_and_expire_on_their_own_clocks():
    fakes = Fakes()
    status = CliStatus(run=fakes.run, fetch=fakes.fetch, clock=fakes.clock)
    status.status(AGENTS[:1])
    status.status(AGENTS[:1])
    assert fakes.runs == ["claude"]
    assert len(fakes.fetches) == 1
    fakes.now += INSTALLED_TTL + 1
    status.status(AGENTS[:1])
    assert fakes.runs == ["claude", "claude"]  # the binary is re-asked (a brew upgrade shows up)
    assert len(fakes.fetches) == 1  # the registry is not, for an hour
    fakes.now += LATEST_TTL
    status.status(AGENTS[:1])
    assert len(fakes.fetches) == 2 and fakes.runs == ["claude"] * 3
    status.status(AGENTS[:1], force=True)
    assert fakes.runs == ["claude"] * 4 and len(fakes.fetches) == 3  # the foot's click re-checks now


def test_a_failure_is_retried_sooner_than_a_success():
    fakes = Fakes(latest={})
    status = CliStatus(run=fakes.run, fetch=fakes.fetch, clock=fakes.clock)
    status.status(AGENTS[:1])
    fakes.now += FAILURE_TTL - 1
    status.status(AGENTS[:1])
    assert len(fakes.fetches) == 1
    fakes.latest = {"@anthropic-ai/claude-code": "2.1.280"}
    fakes.now += 2
    row = status.status(AGENTS[:1])["agents"][0]
    assert len(fakes.fetches) == 2
    assert row["latest"] == "2.1.280" and row["is_outdated"] is True


@pytest.mark.parametrize("command", ["claude", "gemini", "copilot", "grok", "opencode"])
def test_every_npm_published_cli_has_its_package(command):
    assert latest_url(command).startswith("https://registry.npmjs.org/-/package/")


# ── updating a CLI (Settings → Agent CLIs) ──


def test_update_upgrades_the_copy_the_node_runs_the_way_it_was_installed():
    cask = update_plan("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code@latest/2.1.280/claude")
    assert cask["argv"] == ["/opt/homebrew/bin/brew", "upgrade", "--cask", "claude-code@latest"]
    assert cask["then"] == []
    formula = update_plan(
        "opencode", "/opt/homebrew/bin/opencode", "/opt/homebrew/Cellar/opencode/1.18.30_2/bin/opencode"
    )
    assert formula["argv"] == ["/opt/homebrew/bin/brew", "upgrade", "opencode"]
    scoped = update_plan(
        "gemini", "/opt/homebrew/bin/gemini", "/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js"
    )
    assert scoped["argv"] == ["/opt/homebrew/bin/npm", "install", "-g", "@google/gemini-cli@latest"]
    windows = update_plan(
        "copilot",
        r"C:\Users\me\AppData\Roaming\npm\copilot.cmd",
        r"C:\Users\me\AppData\Roaming\npm\copilot.cmd",
        is_windows=True,
    )
    assert windows["argv"] == [
        "npm.cmd",
        "install",
        "-g",
        "--prefix",
        r"C:\Users\me\AppData\Roaming\npm",
        "@github/copilot@latest",
    ]
    cursor = update_plan(
        "agent", "/Users/me/.local/bin/agent", "/Users/me/.local/share/cursor-agent/versions/2026.09.18/cursor-agent"
    )
    assert cursor["argv"] == ["/Users/me/.local/bin/agent", "update"]
    assert update_plan("agy", "/Users/me/.local/bin/agy", "/Users/me/.local/bin/agy")["argv"][1:] == ["update"]


def test_native_windows_grok_uses_its_own_updater_not_a_second_npm_install():
    binary = r"C:\Users\me\.grok\bin\grok.exe"
    plan = update_plan("grok", binary, binary, is_windows=True)
    assert plan["argv"] == [binary, "update"]
    assert plan["how"] == "its own updater"


def test_winget_copilot_updates_only_the_recognized_package():
    binary = r"C:\Users\me\AppData\Local\Microsoft\WinGet\Links\copilot.exe"
    resolved = (
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages"
        r"\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\copilot.exe"
    )
    plan = update_plan("copilot", binary, resolved, is_windows=True)
    assert plan["argv"] == [
        "winget",
        "upgrade",
        "--id",
        "GitHub.Copilot",
        "--exact",
        "--source",
        "winget",
        "--silent",
        "--disable-interactivity",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ]
    assert plan["how"] == "WinGet"
    assert plan["then"] == []
    for unknown in (
        r"C:\custom\copilot.exe",
        resolved.replace("GitHub.Copilot_", "Other.Copilot_"),
        resolved.replace("WinGet", "OtherManager"),
    ):
        assert update_plan("copilot", binary, unknown, is_windows=True)["argv"] == []


def test_windows_version_probe_resolves_cmd_shims(monkeypatch):
    from types import SimpleNamespace

    from agent_cli_bridge import cli_status

    binary = r"C:\Users\me\AppData\Roaming\npm\copilot.cmd"
    monkeypatch.setattr(cli_status, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cli_status.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cli_status.shutil, "which", lambda command: binary)
    calls = []

    def run(argv, **options):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "1.0.88", "")

    monkeypatch.setattr(cli_status.subprocess, "run", run)
    assert "1.0.88" in cli_status.run_version("copilot")
    assert calls == [[binary, "--version"]]


def test_windows_update_resolves_npm_from_path_and_preserves_the_target_prefix(monkeypatch):
    from types import SimpleNamespace

    from agent_cli_bridge import cli_status

    binary = r"C:\Users\me\AppData\Roaming\npm\copilot.cmd"
    npm = r"C:\Program Files\nodejs\npm.cmd"
    plan = update_plan("copilot", binary, binary, is_windows=True)
    monkeypatch.setattr(cli_status, "os", SimpleNamespace(name="nt", environ={}, pathsep=";"))
    monkeypatch.setattr(cli_status.shutil, "which", lambda command: npm if command == "npm.cmd" else None)
    calls = []

    def run(argv, **options):
        calls.append((argv, options))
        return subprocess.CompletedProcess(argv, 0, "updated", "")

    monkeypatch.setattr(cli_status.subprocess, "run", run)
    assert cli_status.run_update(plan["argv"]) == (0, "updated")
    assert calls[0][0] == [npm, *plan["argv"][1:]]
    assert not calls[0][1].get("shell")
    assert plan["argv"][0] == "npm.cmd"  # the plan itself is not mutated


def test_the_stable_claude_cask_is_switched_to_its_latest_twin_download_first():
    """The `claude-code` cask tracks the stable channel: `brew upgrade` says "already installed"
    while npm's `latest` (what the foot compares with) is ahead. Updating it means switching to
    `claude-code@latest` — fetched before anything is uninstalled."""
    plan = update_plan("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code/2.1.267/claude")
    assert plan["argv"] == ["/opt/homebrew/bin/brew", "fetch", "--cask", "claude-code@latest"]
    assert plan["then"] == [
        ["/opt/homebrew/bin/brew", "uninstall", "--cask", "claude-code"],
        ["/opt/homebrew/bin/brew", "install", "--cask", "claude-code@latest"],
    ]
    assert "claude-code@latest" in plan["how"] and "stable" in plan["how"]


def test_a_cli_with_no_known_updater_gets_a_hint_not_a_guess():
    plan = update_plan("gemini", "/usr/local/bin/gemini", "/usr/local/bin/gemini")
    assert plan["argv"] == []
    assert plan["hint"] == "npm install -g @google/gemini-cli@latest"
    assert update_plan("mystery", "/usr/bin/mystery", "/usr/bin/mystery")["argv"] == []


def test_a_package_folder_that_is_not_a_package_name_is_not_installed():
    for folder in ("--registry=evil", "-g", "@scope/..%2f"):
        plan = update_plan("gemini", "/x/bin/gemini", f"/x/lib/node_modules/{folder}/bin.js")
        assert plan["argv"] == [], folder


def _update_host(tmp_path, updates, agents=None, busy=()):
    """An AgentHost whose CLIs and updater are the test's, never this machine's."""
    from agent_cli_bridge.host import AgentHost

    fakes = Fakes()
    provided = agents or [
        {"command": "claude", "name": "Claude Code", "flavor": "claude", "binary_found": True, "path": "/usr/bin/true"},
        {"command": "agent", "name": "Cursor Agent", "flavor": "cursor", "binary_found": False, "path": ""},
    ]

    def runner(argv):
        updates.append(list(argv))
        return 0, "updated"

    host = AgentHost(
        known_models=tmp_path / "known.json",
        agents_provider=lambda: provided,
        home=tmp_path / "home",
        env={},
        cli_status=CliStatus(run=fakes.run, fetch=fakes.fetch, clock=fakes.clock),
        update_runner=runner,
        is_busy=lambda command: command in busy,
    )
    return host, fakes


def test_the_host_only_updates_a_cli_it_found_and_never_one_mid_reply(tmp_path):
    updates = []
    host, fakes = _update_host(tmp_path, updates, busy={"claude"})
    with pytest.raises(ValueError, match="No agent CLI"):
        host.update("rm")
    with pytest.raises(ValueError, match="No agent CLI"):
        host.update("agent")  # known spec, but its binary is not on this machine
    with pytest.raises(ValueError, match="answering a chat"):
        host.update("claude")
    assert updates == []

    host._is_busy = lambda command: False  # the reply ended: the update may run
    result = host.update("claude")
    assert result["ok"] is True
    assert updates == [["/usr/bin/true", "update"]]  # its own updater: /usr/bin is neither brew nor npm
    # The version is read again after the update, not served from the cache.
    assert fakes.runs.count("claude") == 1
    assert result["status"]["agents"][0]["command"] == "claude"


def _stable_cask_claude(tmp_path):
    """A fake Homebrew cask, without requiring Windows symlink privileges."""
    real = tmp_path / "Caskroom" / "claude-code" / "2.1.267" / "claude"
    real.parent.mkdir(parents=True)
    real.write_text("#!/bin/sh\n")
    return [{"command": "claude", "name": "Claude Code", "flavor": "claude", "binary_found": True, "path": str(real)}]


def test_a_channel_switch_runs_every_step_in_order(tmp_path):
    updates = []
    host, _ = _update_host(tmp_path, updates, agents=_stable_cask_claude(tmp_path))
    result = host.update("claude")
    brew = str(tmp_path / "bin" / "brew")
    assert result["ok"] is True
    assert updates == [
        [brew, "fetch", "--cask", "claude-code@latest"],
        [brew, "uninstall", "--cask", "claude-code"],
        [brew, "install", "--cask", "claude-code@latest"],
    ]
    assert result["output"].count("$ ") == 3  # each step's command heads its output
    assert "claude-code@latest" in result["how"]


def _latest_cask_claude(tmp_path):
    """A fake Homebrew prefix: `bin/claude` → `Caskroom/claude-code@latest/2.1.280/claude`."""
    real = tmp_path / "Caskroom" / "claude-code@latest" / "2.1.280" / "claude"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"old-claude")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "claude").symlink_to(real)
    return [
        {
            "command": "claude",
            "name": "Claude Code",
            "flavor": "claude",
            "binary_found": True,
            "path": str(tmp_path / "bin" / "claude"),
        }
    ]


def test_the_release_url_is_anthropic_s_and_rejects_anything_else():
    assert claude_release_url("2.1.281", "Darwin", "arm64") == (
        "https://downloads.claude.ai/claude-code-releases/2.1.281/darwin-arm64/claude"
    )
    assert claude_release_url("2.1.281", "Linux", "x86_64").endswith("/linux-x64/claude")
    for version in ("", "latest", "2.1.281-beta", "2.1.281;rm", "../2.1.281"):
        with pytest.raises(ClaudeReleaseError):
            claude_release_url(version, "Darwin", "arm64")
    with pytest.raises(ClaudeReleaseError):
        claude_release_url("2.1.281", "Darwin", "ppc")


def test_only_the_latest_cask_file_itself_may_be_replaced(tmp_path):
    agents = _latest_cask_claude(tmp_path)
    real = os.path.realpath(agents[0]["path"])
    assert is_claude_latest_cask_binary(real)
    assert not is_claude_latest_cask_binary(agents[0]["path"])  # the bin/ symlink is not the cask file
    stray = tmp_path / "claude"
    stray.write_bytes(b"nope")
    with pytest.raises(ClaudeReleaseError, match="not the claude-code@latest"):
        install_published_claude(str(stray), "2.1.281", download=lambda url, dest: None, verify=lambda path: None)


def test_a_failed_signature_check_leaves_the_cask_binary_in_place(tmp_path):
    real = Path(os.path.realpath(_latest_cask_claude(tmp_path)[0]["path"]))

    def download(url, dest):
        assert url.endswith("/2.1.281/darwin-arm64/claude")
        dest.write_bytes(b"unsigned")

    def reject(path):
        raise ClaudeReleaseError("not signed by Anthropic")

    with pytest.raises(ClaudeReleaseError, match="not signed"):
        install_published_claude(
            str(real), "2.1.281", system="Darwin", machine="arm64", download=download, verify=reject
        )
    assert real.read_bytes() == b"old-claude"
    assert not real.with_name(".claude.agent-cli-bridge-download").exists()


def test_a_signed_download_replaces_only_the_cask_file(tmp_path):
    link = Path(_latest_cask_claude(tmp_path)[0]["path"])
    real = Path(os.path.realpath(link))

    def download(url, dest):
        dest.write_bytes(b"new-claude")

    note = install_published_claude(
        str(real),
        "2.1.281",
        system="Darwin",
        machine="arm64",
        download=download,
        verify=lambda path: None,
    )
    assert b"2.1.281" in note.encode()
    assert real.read_bytes() == b"new-claude"
    assert link.read_bytes() == b"new-claude"  # the Homebrew symlink still points here
    assert not real.with_name(".claude.agent-cli-bridge-download").exists()


def test_catch_up_does_nothing_when_homebrew_is_already_current():
    code, note = catch_up_claude_cask("/opt/homebrew/Caskroom/claude-code@latest/2.1.281/claude", "2.1.281", "2.1.281")
    assert (code, note) == (0, "")
    code, note = catch_up_claude_cask("/usr/local/bin/claude", "2.1.280", "2.1.281")
    assert (code, note) == (0, "")


def test_catch_up_explains_when_npm_is_ahead_of_the_binary_anthropic_publishes():
    def fetch(url):
        assert url == CLAUDE_RELEASE_LATEST_URL
        return b"2.1.280\n"

    code, note = catch_up_claude_cask(
        "/opt/homebrew/Caskroom/claude-code@latest/2.1.280/claude", "2.1.280", "2.1.281", fetch=fetch
    )
    assert code == 1
    assert "2.1.280" in note and "2.1.281" in note and "npm" in note


def test_a_latest_cask_that_brew_will_not_upgrade_installs_anthropics_binary(tmp_path, monkeypatch):
    """The warning in the desk: brew exits 0, 'Not upgrading claude-code@latest, the latest version
    is already installed', while npm's latest (and Anthropic's download) is newer."""
    updates = []
    installed = []
    host, fakes = _update_host(tmp_path, updates, agents=_latest_cask_claude(tmp_path))
    fakes.latest = {"@anthropic-ai/claude-code": "2.1.281"}

    def fetch(url):
        fakes.fetches.append(url)
        if url == CLAUDE_RELEASE_LATEST_URL:
            return b"2.1.281\n"
        return Fakes.fetch(fakes, url)

    host._status._fetch = fetch

    def installer(dest, version):
        installed.append((dest, version))
        return f"Installed Anthropic's Claude Code {version} over the Homebrew cask"

    monkeypatch.setattr("agent_cli_bridge.cli_status.install_published_claude", installer)
    host._run_update = lambda argv: (
        updates.append(argv)
        or (0, "Warning: Not upgrading claude-code@latest, the latest version is already installed")
    )
    result = host.update("claude")
    real = os.path.realpath(host._agents_provider()[0]["path"])
    assert result["ok"] is True
    assert [argv[1:] for argv in updates] == [["upgrade", "--cask", "claude-code@latest"]]
    assert installed == [(real, "2.1.281")]
    assert "already installed" in result["output"]
    assert "Installed Anthropic's Claude Code 2.1.281" in result["output"]
    assert "Anthropic" in result["how"]


def test_a_latest_cask_stays_put_when_the_anthropic_install_fails(tmp_path, monkeypatch):
    updates = []
    host, fakes = _update_host(tmp_path, updates, agents=_latest_cask_claude(tmp_path))
    fakes.latest = {"@anthropic-ai/claude-code": "2.1.281"}

    def fetch(url):
        if url == CLAUDE_RELEASE_LATEST_URL:
            return b"2.1.281\n"
        return Fakes.fetch(fakes, url)

    host._status._fetch = fetch

    def installer(dest, version):
        raise ClaudeReleaseError("Anthropic's signature check failed: code object is not signed")

    monkeypatch.setattr("agent_cli_bridge.cli_status.install_published_claude", installer)
    result = host.update("claude")
    assert result["ok"] is False
    assert "signature" in result["output"]
    assert Path(os.path.realpath(host._agents_provider()[0]["path"])).read_bytes() == b"old-claude"


def test_a_channel_switch_stops_at_the_first_failure_so_a_failed_download_uninstalls_nothing(tmp_path):
    updates = []
    host, _ = _update_host(tmp_path, updates, agents=_stable_cask_claude(tmp_path))
    host._run_update = lambda argv: updates.append(argv) or (1, "curl: (6) Could not resolve host")
    result = host.update("claude")
    assert result["ok"] is False
    assert [argv[1] for argv in updates] == ["fetch"]  # no uninstall, no install
    assert "Could not resolve host" in result["output"]


# -- macOS Gatekeeper: a quarantined CLI is "Not Opened / Move to Trash" at its next launch ------


def test_clear_macos_quarantine_strips_only_that_attribute(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_bytes(b"signed")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class Result:
            returncode = 0
            stdout = "0181;6ac2b6f7;;uuid\n" if argv[1] == "-p" else ""
            stderr = ""

        return Result()

    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Darwin")
    monkeypatch.setattr("agent_cli_bridge.cli_status.subprocess.run", fake_run)
    assert clear_macos_quarantine(str(binary)) is True
    assert [call[:3] for call in calls] == [
        ["/usr/bin/xattr", "-p", "com.apple.quarantine"],
        ["/usr/bin/xattr", "-d", "com.apple.quarantine"],
    ]
    assert calls[0][3] == str(binary.resolve())


def test_clear_macos_quarantine_leaves_a_clean_binary_alone(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_bytes(b"signed")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class Result:
            returncode = 1
            stdout = ""
            stderr = "No such xattr: com.apple.quarantine"

        return Result()

    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Darwin")
    monkeypatch.setattr("agent_cli_bridge.cli_status.subprocess.run", fake_run)
    assert clear_macos_quarantine(str(binary)) is False
    assert len(calls) == 1 and calls[0][1] == "-p"


def test_clear_macos_quarantine_is_a_noop_off_macos(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_bytes(b"signed")
    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Linux")

    def fail_run(*args, **kwargs):
        raise AssertionError("xattr off macOS")

    monkeypatch.setattr("agent_cli_bridge.cli_status.subprocess.run", fail_run)
    assert clear_macos_quarantine(str(binary)) is False


def test_the_version_probe_clears_quarantine_before_it_runs_the_cli(monkeypatch):
    from agent_cli_bridge import cli_status

    events: list[str] = []
    monkeypatch.setattr(cli_status.shutil, "which", lambda command: f"/opt/bin/{command}")
    monkeypatch.setattr(cli_status, "clear_macos_quarantine", lambda path: events.append(f"clear:{path}") or False)

    def run(argv, **kwargs):
        events.append("run")
        return subprocess.CompletedProcess(argv, 0, stdout="2.1.280 (Claude Code)", stderr="")

    monkeypatch.setattr(cli_status.subprocess, "run", run)
    assert "2.1.280" in cli_status.run_version("claude")
    assert events == ["clear:/opt/bin/claude", "run"]


def test_replacing_the_cask_file_clears_quarantine_on_the_new_binary(tmp_path, monkeypatch):
    real = Path(os.path.realpath(_latest_cask_claude(tmp_path)[0]["path"]))
    cleared: list[str] = []
    monkeypatch.setattr(
        "agent_cli_bridge.cli_status.clear_macos_quarantine",
        lambda path: cleared.append(path) or True,
    )
    install_published_claude(
        str(real),
        "2.1.281",
        system="Darwin",
        machine="arm64",
        download=lambda url, dest: dest.write_bytes(b"new-claude"),
        verify=lambda path: None,
    )
    assert cleared == [str(real)]


def test_an_update_clears_the_download_quarantine_homebrew_leaves_behind(tmp_path, monkeypatch):
    """A cask install stamps quarantine, and Gatekeeper then offers to trash `claude`: the mark
    has to be gone once the update returns."""
    cleared: list[str] = []
    host, _ = _update_host(tmp_path, [])
    monkeypatch.setattr("agent_cli_bridge.host.clear_macos_quarantine", lambda path: cleared.append(path) or True)
    result = host.update("claude")
    assert result["ok"] is True
    # Once before the version probe (that launch is the dialog), once after the catch-up in
    # case the direct download arrived quarantined.
    assert cleared == ["/usr/bin/true", "/usr/bin/true"]


def test_a_cask_upgrade_drops_quarantine_before_reading_the_new_version(tmp_path, monkeypatch):
    """brew stamps quarantine, then the catch-up runs `claude --version`. That order is the dialog."""
    events: list[str] = []
    host, fakes = _update_host(tmp_path, [], agents=_latest_cask_claude(tmp_path))
    fakes.latest = {"@anthropic-ai/claude-code": "2.1.267"}  # same as the installed version: no download

    def run(command):
        events.append(f"version:{command}")
        return Fakes.run(fakes, command)

    host._status._run = run
    monkeypatch.setattr("agent_cli_bridge.host.clear_macos_quarantine", lambda path: events.append(f"clear:{path}") or True)
    result = host.update("claude")
    assert result["ok"] is True
    binary = str(tmp_path / "bin" / "claude")
    assert events[0] == f"clear:{binary}"
    assert events.index(f"clear:{binary}") < events.index("version:claude")


def test_warm_up_and_clear_quarantine_drop_a_mark_an_earlier_update_left(tmp_path, monkeypatch):
    cleared: list[str] = []
    host, _ = _update_host(tmp_path, [])
    monkeypatch.setattr("agent_cli_bridge.host.clear_macos_quarantine", lambda path: cleared.append(path) or True)
    host.warm()
    assert cleared == ["/usr/bin/true"]  # Cursor has no binary here: nothing to clear
    assert host.clear_quarantine("claude") is True
    assert host.clear_quarantine("rm") is False  # an unknown command touches nothing
    assert cleared == ["/usr/bin/true", "/usr/bin/true"]


# ── uninstalling a CLI (Settings › Agents) ──


def test_uninstall_removes_the_copy_the_node_runs_the_way_it_was_installed(tmp_path):
    cask = uninstall_plan("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code@latest/2.1.280/claude")
    assert cask["argv"] == ["/opt/homebrew/bin/brew", "uninstall", "--cask", "claude-code@latest"]
    formula = uninstall_plan("opencode", "/opt/homebrew/bin/opencode", "/opt/homebrew/Cellar/opencode/2.0.20/bin/opencode")
    assert formula["argv"] == ["/opt/homebrew/bin/brew", "uninstall", "opencode"]
    scoped = uninstall_plan(
        "grok", "/opt/homebrew/bin/grok", "/opt/homebrew/lib/node_modules/@xai-official/grok/bin/grok-native"
    )
    assert scoped["argv"] == ["/opt/homebrew/bin/npm", "uninstall", "-g", "@xai-official/grok"]
    windows = uninstall_plan(
        "copilot", r"C:\Users\me\AppData\Roaming\npm\copilot.cmd", r"C:\Users\me\AppData\Roaming\npm\copilot.cmd",
        is_windows=True,
    )
    assert windows["argv"] == ["npm.cmd", "uninstall", "-g", "--prefix", r"C:\Users\me\AppData\Roaming\npm", "@github/copilot"]
    # Something the host cannot tell how it was installed is a hint, never a guess at what to delete.
    unknown = uninstall_plan("agy", "/Users/me/.local/bin/agy", "/Users/me/.local/bin/agy", home=tmp_path)
    assert unknown["argv"] == [] and "remove" not in unknown and "/Users/me/.local/bin/agy" in unknown["hint"]


def test_a_native_install_removes_only_its_own_folder_and_links(tmp_path):
    share = tmp_path / ".local" / "share" / "cursor-agent"
    binary_dir = share / "versions" / "2026.10.01"
    binary_dir.mkdir(parents=True)
    (binary_dir / "cursor-agent").write_text("bin")
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "agent").symlink_to(binary_dir / "cursor-agent")
    (bin_dir / "cursor-agent").symlink_to(binary_dir / "cursor-agent")
    other = tmp_path / "elsewhere"
    other.write_text("x")
    (bin_dir / "claude").symlink_to(other)  # not Cursor's: stays
    resolved = str((binary_dir / "cursor-agent").resolve())
    plan = uninstall_plan("agent", str(bin_dir / "agent"), resolved, home=tmp_path.resolve())
    assert plan["remove"] == {
        "dir": str(tmp_path.resolve() / ".local" / "share" / "cursor-agent"),
        "links": [str(tmp_path.resolve() / ".local" / "bin" / "agent"), str(tmp_path.resolve() / ".local" / "bin" / "cursor-agent")],
    }
    code, output = remove_native_install(plan["remove"])
    assert code == 0 and "Removed" in output
    assert not share.exists() and not (bin_dir / "agent").is_symlink() and not (bin_dir / "cursor-agent").is_symlink()
    assert (bin_dir / "claude").is_symlink() and other.exists()


def test_a_winget_package_is_removed_by_its_own_id():
    agy = uninstall_plan(
        "agy",
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Links\agy.exe",
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\Google.AntigravityCLI_Microsoft.Winget.Source_8wekyb3d8bbwe\agy.EXE",
        is_windows=True,
    )
    assert agy["argv"][:4] == ["winget", "uninstall", "--id", "Google.AntigravityCLI"] and agy["how"] == "WinGet"
    # Another package's folder never names a WinGet id for this CLI.
    other = uninstall_plan(
        "agy",
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\agy.exe",
        r"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\agy.exe",
        is_windows=True,
    )
    assert other["argv"] == [] and "hint" in other


def test_grok_own_installer_removes_only_its_bin_folder(tmp_path):
    grok_home = tmp_path / ".grok"
    bin_dir = grok_home / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "grok").write_text("bin")
    (bin_dir / "agent").write_text("bin")
    (grok_home / "auth.json").write_text("{}")  # the sign-in stays
    binary = str(bin_dir / "grok")
    plan = uninstall_plan("grok", binary, binary, home=tmp_path)
    assert plan["remove"] == {"dir": str(bin_dir), "links": []}
    code, _ = remove_native_install(plan["remove"])
    assert code == 0 and not bin_dir.exists() and (grok_home / "auth.json").exists()
    # A grok elsewhere, or another CLI inside ~/.grok/bin, is never removed as Grok's folder.
    bin_dir.mkdir()
    assert "remove" not in uninstall_plan("grok", "/usr/local/bin/grok", "/usr/local/bin/grok", home=tmp_path)
    assert "remove" not in uninstall_plan("agy", str(bin_dir / "agy"), str(bin_dir / "agy"), home=tmp_path)


def test_a_binary_outside_the_native_folder_is_never_removed_as_native(tmp_path):
    share = tmp_path / ".local" / "share" / "claude"
    share.mkdir(parents=True)
    plan = uninstall_plan("claude", "/usr/local/bin/claude", "/usr/local/lib/claude", home=tmp_path)
    assert "remove" not in plan and plan["argv"] == []


# ── installing a missing CLI (Settings › Agents) ──


def test_install_uses_each_vendors_installer_and_never_a_name_it_does_not_know(tmp_path):
    none = {"which": lambda name: None, "find": lambda paths: ""}
    assert install_plan("claude", home=tmp_path, **none)["argv"] == [
        "/bin/bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"
    ]
    npm = install_plan("grok", home=tmp_path, which=lambda name: "/usr/local/bin/npm" if name == "npm" else None)
    assert npm["argv"] == ["/usr/local/bin/npm", "install", "-g", "@xai-official/grok"] and npm["how"] == "npm"
    brew = install_plan(
        "gemini", home=tmp_path, which=lambda name: None,
        find=lambda paths: "/opt/homebrew/bin/brew" if "/opt/homebrew/bin/brew" in paths else "",
    )
    assert brew["argv"] == ["/opt/homebrew/bin/brew", "install", "node"]
    assert brew["then"] == [["/opt/homebrew/bin/npm", "install", "-g", "@google/gemini-cli"]]
    bare = install_plan("copilot", home=tmp_path, **none)
    assert bare["argv"] == [] and "npm install -g @github/copilot" in bare["hint"]
    assert install_plan("rm -rf /", home=tmp_path, **none)["argv"] == []
    on_path = {"which": lambda name: name, "find": lambda paths: ""}
    windows = install_plan("agy", is_windows=True, **on_path)
    assert windows["argv"][:5] == ["winget", "install", "-e", "--id", "Google.AntigravityCLI"]
    assert install_plan("claude", is_windows=True, **on_path)["argv"][0] == "powershell"


def test_windows_installers_are_found_by_full_path_off_a_background_path(monkeypatch):
    # A node started at login may not have PowerShell's or WinGet's folder on its PATH: a bare
    # "powershell" / "winget" then fails with WinError 2 (or worse) instead of installing.
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    winget = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe"
    both = {"which": lambda name: None, "find": lambda paths: next((p for p in paths if p in (powershell, winget)), "")}
    cursor = install_plan("agent", is_windows=True, **both)
    assert cursor["argv"][0] == powershell and cursor["manual"] == "irm 'https://cursor.com/install?win32=true' | iex"
    agy = install_plan("agy", is_windows=True, **both)
    assert agy["argv"][:5] == [winget, "install", "-e", "--id", "Google.AntigravityCLI"] and agy["how"] == "WinGet"
    # No WinGet at all: Google's own PowerShell script instead of a launch that cannot work.
    no_winget = {"which": lambda name: None, "find": lambda paths: powershell if powershell in paths else ""}
    fallback = install_plan("agy", is_windows=True, **no_winget)
    assert fallback["argv"][0] == powershell
    assert fallback["argv"][-1] == "irm https://antigravity.google/cli/install.ps1 | iex"
    # Nothing to run with: a hint the owner can follow, never a bare name.
    nothing = install_plan("agent", is_windows=True, which=lambda name: None, find=lambda paths: "")
    assert nothing["argv"] == [] and "cursor.com/install" in nothing["hint"]


def test_an_installer_that_cannot_start_says_which_program(monkeypatch):
    from agent_cli_bridge import cli_status

    def refuse(argv, **options):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(cli_status.subprocess, "run", refuse)
    code, output = cli_status.run_update(["/no/such/powershell.exe", "-Command", "x"])
    assert code == -1 and output.startswith("Could not start /no/such/powershell.exe:")
