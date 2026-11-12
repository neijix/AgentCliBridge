"""AgentHost: one machine's CLIs, their models, versions and the refusals around update and sign-in."""

from pathlib import Path

import pytest

from agent_cli_bridge.host import AgentHost


class Catalog:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.refreshed = []
        self.gateways = []
        self.forgotten = []

    def merge(self, agent):
        return {
            "models": list(agent.get("models") or []),
            "new_models": ["extra"] if agent["command"] == "grok" else [],
        }

    def refresh(self, agents, force=False, claude_gateway=None):
        if self.fail:
            raise RuntimeError("the CLI printed nothing useful")
        self.refreshed.append(([a["command"] for a in agents], force))
        self.gateways.append(claude_gateway)

    def forget(self, command):
        self.forgotten.append(command)


class Status:
    def __init__(self):
        self.forgotten = []

    def status(self, agents, force=False):
        return {
            "checked_at": 1,
            "agents": [
                {
                    "command": a["command"],
                    "name": a["name"],
                    "installed": "1.0",
                    "latest": "1.0",
                    "is_outdated": False,
                    "source": "test",
                    "error": "",
                    "can_sign_in": False,
                    "needs_code": False,
                }
                for a in agents
            ],
        }

    def forget(self, command):
        self.forgotten.append(command)

    def installed(self, command):
        return {"version": "1.0"}

    def latest(self, command, force=False):
        return {"version": "1.0"}

    @property
    def fetch(self):
        return lambda url: b""


def host(tmp_path, agents, *, catalog=None, busy=(), disabled=(), runner=None, binaries=(), enabled=None):
    return AgentHost(
        known_models=tmp_path / "known.json",
        agents_provider=lambda: agents,
        home=tmp_path,
        env={"CLAUDE_CODE_USE_BEDROCK": "1"},
        model_catalog=catalog or Catalog(),
        cli_status=Status(),
        is_busy=lambda command: command in busy,
        disabled_provider=lambda: set(disabled),
        enabler=(enabled.append if enabled is not None else lambda names: None),
        binary_resolver=lambda command: f"/bin/{command}" if command in binaries else None,
        **({"update_runner": runner} if runner else {}),
    )


AGENTS = [
    {
        "command": "claude",
        "name": "Claude Code",
        "flavor": "claude",
        "models": ["opus"],
        "binary_found": True,
        "path": "/bin/claude",
    },
    {
        "command": "grok",
        "name": "Grok CLI",
        "flavor": "grok",
        "models": ["grok-4.6"],
        "binary_found": True,
        "path": "/bin/grok",
    },
    {
        "command": "agy",
        "name": "Google Antigravity",
        "flavor": "antigravity",
        "models": [],
        "binary_found": False,
        "path": "",
    },
    {
        "command": "agent",
        "name": "Cursor Agent",
        "flavor": "cursor",
        "models": ["auto"],
        "binary_found": True,
        "path": "/home/me/.grok/bin/agent",
    },
]


def test_agents_lists_only_what_this_machine_can_run_and_tags_claudes_account(tmp_path):
    rows = host(tmp_path, AGENTS).agents()
    assert [row["command"] for row in rows] == ["claude", "grok"]  # no binary, and the Grok collision, stay out
    claude, grok = rows
    assert claude["models"] == ["opus"] and claude["account"] == {"kind": "work", "detail": "Bedrock"}
    assert grok["new_models"] == ["extra"] and "account" not in grok
    assert host(tmp_path, AGENTS).installed_agents() == [
        {"command": "claude", "name": "Claude Code", "path": "/bin/claude"},
        {"command": "grok", "name": "Grok CLI", "path": "/bin/grok"},
    ]


def test_status_rows_carry_the_flavor_and_claudes_account(tmp_path):
    rows = {row["command"]: row for row in host(tmp_path, AGENTS).status()["agents"]}
    assert rows["claude"]["flavor"] == "claude"
    assert rows["claude"]["account"]["kind"] == "work"
    assert rows["grok"]["flavor"] == "grok" and "account" not in rows["grok"]


def test_a_model_refresh_that_fails_is_swallowed_and_skips_a_cli_with_no_binary(tmp_path):
    catalog = Catalog(fail=True)
    host(tmp_path, AGENTS, catalog=catalog).refresh_models(force=True)  # must not raise
    catalog.fail = False
    host(tmp_path, AGENTS, catalog=catalog).refresh_models()
    assert catalog.refreshed == [(["claude", "grok"], False)]


def test_models_are_refreshed_with_the_gateway_claude_code_talks_to(tmp_path):
    catalog = Catalog()
    gateway_env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}
    AgentHost(
        agents_provider=lambda: AGENTS, home=tmp_path, env=gateway_env, model_catalog=catalog, cli_status=Status()
    ).refresh_models()
    host(tmp_path, AGENTS, catalog=catalog).refresh_models()  # Bedrock: no gateway to read
    assert catalog.gateways == ["http://127.0.0.1:4000", None]


def test_update_and_sign_in_refuse_an_unknown_cli_and_the_grok_binary_named_agent(tmp_path):
    one = host(tmp_path, AGENTS)
    with pytest.raises(ValueError, match="No agent CLI"):
        one.update("rm")
    with pytest.raises(ValueError, match="Grok"):
        one.sign_in("agent")
    with pytest.raises(ValueError, match="answering a chat"):
        host(tmp_path, AGENTS, busy={"claude"}).update("claude")


def test_uninstall_refuses_like_update_and_runs_the_plan(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="No agent CLI"):
        host(tmp_path, AGENTS).uninstall("rm")
    with pytest.raises(ValueError, match="Grok"):
        host(tmp_path, AGENTS).uninstall("agent")
    with pytest.raises(ValueError, match="answering a chat"):
        host(tmp_path, AGENTS, busy={"grok"}).uninstall("grok")
    ran = []
    npm_grok = [dict(AGENTS[1], path="/opt/homebrew/bin/grok")]
    monkeypatch.setattr(
        "agent_cli_bridge.host.os.path.realpath",
        lambda path: "/opt/homebrew/lib/node_modules/@xai-official/grok/bin/grok-native",
    )
    one = AgentHost(
        known_models=tmp_path / "known.json", agents_provider=lambda: npm_grok, home=tmp_path,
        model_catalog=Catalog(), cli_status=Status(), update_runner=lambda argv: (ran.append(argv), (0, "removed"))[1],
    )
    result = one.uninstall("grok")
    assert ran == [["/opt/homebrew/bin/npm", "uninstall", "-g", "@xai-official/grok"]]
    assert result["ok"] and result["how"] == "npm" and result["output"] == "removed"


def test_missing_lists_the_known_clis_not_offered_including_turned_off_ones(tmp_path):
    rows = host(tmp_path, AGENTS, disabled={"gemini", "copilot"}, binaries={"copilot"}).missing_agents()
    # claude and grok run; Antigravity has no binary and Cursor's name is Grok's binary: both installable.
    assert [row["command"] for row in rows] == ["agent", "agy", "gemini", "copilot", "opencode"]
    flags = {row["command"]: (row["is_disabled"], row["is_installed"]) for row in rows}
    assert flags["agy"] == (False, False)
    assert flags["gemini"] == (True, False)  # turned off and absent: Install
    assert flags["copilot"] == (True, True)  # turned off but there: Turn on
    status = host(tmp_path, AGENTS).status()
    assert {row["command"] for row in status["missing"]} >= {"agy", "gemini"}


def test_install_turns_a_disabled_cli_back_on(tmp_path, monkeypatch):
    enabled, ran = [], []
    runner = lambda argv: (ran.append(argv), (0, "done"))[1]  # noqa: E731
    one = host(tmp_path, AGENTS, disabled={"copilot"}, binaries={"copilot"}, enabled=enabled, runner=runner)
    result = one.install("copilot")  # already installed: nothing runs, the settings file lets it back
    assert result["ok"] and result["how"] == "turned on" and ran == [] and enabled == [{"copilot"}]
    monkeypatch.setattr("agent_cli_bridge.host.os.name", "posix")
    enabled.clear()
    failing = host(tmp_path, AGENTS, disabled={"agy", "antigravity"}, enabled=enabled, runner=lambda argv: (1, "no"))
    assert not failing.install("agy")["ok"] and enabled == []  # a failed install leaves it off
    one = host(tmp_path, AGENTS, disabled={"antigravity"}, enabled=enabled, runner=runner)
    assert one.install("agy")["ok"] and enabled == [{"agy", "antigravity"}]


def test_install_refuses_what_is_installed_or_unknown_and_runs_the_plan(tmp_path, monkeypatch):
    for command in ("claude", "rm"):
        with pytest.raises(ValueError, match="cannot install|can install"):
            host(tmp_path, AGENTS).install(command)
    ran = []
    monkeypatch.setattr("agent_cli_bridge.host.os.name", "posix")
    result = host(tmp_path, AGENTS, runner=lambda argv: (ran.append(argv), (0, "done"))[1]).install("agy")
    assert ran == [["/bin/bash", "-c", "curl -fsSL https://antigravity.google/cli/install.sh | bash"]]
    assert result["ok"] and result["how"] == "its install script" and "missing" in result["status"]


def test_update_and_install_share_one_step_loop_that_stops_at_the_first_failure(tmp_path, monkeypatch):
    source = (Path(__file__).parents[1] / "agent_cli_bridge" / "host.py").read_text()
    assert source.count("def _run_plan_steps(") == 1
    assert source.count("_run_plan_steps(") == 3  # the definition, update, and install
    assert source.count("for argv in steps:") == 1

    calls: list[list[str]] = []

    def runner(argv: list[str]) -> tuple[int, str]:
        calls.append(list(argv))
        if argv[0] == "fail":
            return 3, "nope"
        return 0, "ok"

    monkeypatch.setattr("agent_cli_bridge.host.os.name", "posix")
    one = host(tmp_path, AGENTS, runner=runner)
    monkeypatch.setattr(
        "agent_cli_bridge.host.update_plan",
        lambda command, binary, resolved, **kw: {
            "argv": ["brew", "uninstall"], "then": [["brew", "install"]], "how": "Homebrew", "hint": "",
        },
    )
    updated = one.update("grok")
    assert calls == [["brew", "uninstall"], ["brew", "install"]]
    assert updated["ok"] and updated["how"] == "Homebrew"
    assert updated["output"] == "$ brew uninstall\nok\n\n$ brew install\nok"

    calls.clear()
    monkeypatch.setattr(
        "agent_cli_bridge.host.update_plan",
        lambda command, binary, resolved, **kw: {
            "argv": ["npm", "install"], "then": [], "how": "npm", "hint": "",
        },
    )
    single = one.update("grok")
    assert calls == [["npm", "install"]] and single["ok"] and single["output"] == "ok"

    calls.clear()
    monkeypatch.setattr(
        "agent_cli_bridge.host.update_plan",
        lambda command, binary, resolved, **kw: {
            "argv": ["brew", "uninstall"], "then": [["fail"], ["brew", "install"]], "how": "Homebrew", "hint": "",
        },
    )
    failed = one.update("grok")
    assert calls == [["brew", "uninstall"], ["fail"]] and not failed["ok"]
    assert failed["output"] == "$ brew uninstall\nok\n\n$ fail\nnope"

    calls.clear()
    monkeypatch.setattr(
        "agent_cli_bridge.host.install_plan",
        lambda command, **options: {
            "argv": ["brew", "install", "node"],
            "then": [["npm", "install", "-g", "pkg"]],
            "how": "Homebrew Node.js, then npm",
        },
    )
    installed = one.install("agy")
    assert calls == [["brew", "install", "node"], ["npm", "install", "-g", "pkg"]]
    assert installed["ok"] and installed["how"] == "Homebrew Node.js, then npm"
    assert installed["output"] == "$ brew install node\nok\n\n$ npm install -g pkg\nok"

    calls.clear()
    monkeypatch.setattr(
        "agent_cli_bridge.host.install_plan",
        lambda command, **options: {
            "argv": ["fail"], "then": [["npm", "install"]], "how": "npm", "manual": "do it yourself",
        },
    )
    failed_install = one.install("agy")
    assert calls == [["fail"]] and not failed_install["ok"]
    assert failed_install["output"] == "$ fail\nnope\n\nRun it by hand in a PowerShell window: do it yourself"


def test_a_failed_windows_install_names_the_command_to_run_by_hand(tmp_path, monkeypatch):
    plan = {"argv": ["powershell.exe", "-Command", "x"], "then": [], "how": "its install script", "manual": "irm x | iex"}
    monkeypatch.setattr("agent_cli_bridge.host.install_plan", lambda command, **options: plan)
    failed = host(tmp_path, AGENTS, runner=lambda argv: (-1, "Could not start powershell.exe: Access is denied")).install("agy")
    assert not failed["ok"] and failed["output"].endswith("Run it by hand in a PowerShell window: irm x | iex")
    worked = host(tmp_path, AGENTS, runner=lambda argv: (0, "done")).install("agy")
    assert worked["ok"] and "by hand" not in worked["output"]


def test_status_force_and_cli_update_or_install_refresh_models(tmp_path, monkeypatch):
    catalog = Catalog()
    monkeypatch.setattr("agent_cli_bridge.host.os.name", "posix")
    monkeypatch.setattr(
        "agent_cli_bridge.host.update_plan",
        lambda command, binary, resolved, **kw: {"argv": ["/bin/echo", "updated"], "then": [], "how": "npm", "hint": ""},
    )
    one = host(tmp_path, AGENTS, catalog=catalog, runner=lambda argv: (0, "updated"))
    one.status(force=True)
    assert catalog.refreshed[-1] == (["claude", "grok"], True)

    catalog.refreshed.clear()
    result = one.update("grok")
    assert result["ok"]
    assert "grok" in catalog.forgotten
    assert catalog.refreshed == [(["claude", "grok"], False)]

    catalog.refreshed.clear()
    turned_on = host(
        tmp_path, AGENTS, catalog=catalog, disabled={"copilot"}, binaries={"copilot"}, runner=lambda argv: (0, "ok")
    ).install("copilot")
    assert turned_on["ok"] and catalog.refreshed == [(["claude", "grok"], False)]
