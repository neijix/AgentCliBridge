"""Argv construction per flavor (ported from an earlier desktop chat app's test suite)."""
import logging

import pytest

from agent_cli_bridge import (
    PERMISSION_MODES,
    build_argv,
    compose_prompt,
    flavor_for,
    model_args,
    normalize_permission_mode,
)
from agent_cli_bridge.argv import token_file_denials
from agent_cli_bridge.runner import _extract_cursor_text


class TestNormalizePermissionMode:
    """Unknown strings fall back to plan. An omitted mode stays the headless default."""

    def test_unknown_mode_becomes_plan_and_logs_a_warning(self, caplog):
        samples = ("", "Plan", "yolo", "PLAN")
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.argv"):
            for sample in samples:
                assert normalize_permission_mode(sample) == "plan"
        warnings = [r for r in caplog.records if r.name == "agent_cli_bridge.argv"]
        assert len(warnings) == len(samples)
        for sample, record in zip(samples, warnings, strict=True):
            assert record.levelno == logging.WARNING
            assert repr(sample.strip()) in record.getMessage()
            assert "plan" in record.getMessage()

    def test_known_permission_modes_stay_themselves(self, caplog):
        known = ("plan", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions")
        assert tuple(PERMISSION_MODES) == known
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.argv"):
            for mode in known:
                assert normalize_permission_mode(mode) == mode
        assert [r for r in caplog.records if r.name == "agent_cli_bridge.argv"] == []

    def test_omitted_permission_mode_stays_accept_edits(self, caplog):
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.argv"):
            assert normalize_permission_mode(None) == "acceptEdits"
        assert [r for r in caplog.records if r.name == "agent_cli_bridge.argv"] == []


class TestFlavorMapping:
    def test_flavor_mapping(self):
        assert flavor_for("claude") == "claude"
        assert flavor_for("agent") == "cursor"
        assert flavor_for("cursor-agent") == "cursor"
        assert flavor_for("agy") == "antigravity"
        assert flavor_for("gemini") == "gemini"
        assert flavor_for("copilot") == "copilot"
        assert flavor_for("unknown-bin") == "claude"


class TestClaudeArgv:
    def test_claude_argv(self):
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt="hi", system_text="sys",
        )
        assert argv[:2] == ["/bin/claude", "-p"]
        assert argv[-2:] == ["--", "hi"]  # last, so no flag can follow the prompt
        assert "--append-system-prompt" in argv
        assert "sys" in argv
        assert "--allowedTools" in argv
        # Default headless mode: acceptEdits + Write/Edit allowlisted.
        assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
        assert "Write" in argv[argv.index("--allowedTools") + 1]

    def test_a_claude_prompt_that_looks_like_a_flag_stays_the_prompt(self):
        prompt = '--mcp-config={"mcpServers": {}} summarize'
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt=prompt, cli_args=["--strict-mcp-config"],
        )
        assert argv[-2:] == ["--", prompt]
        assert argv.count(prompt) == 1

    def test_claude_can_read_its_prompt_from_stdin(self):
        argv = build_argv(binary="/bin/claude", flavor="claude", prompt="a long page", prompt_on_stdin=True)
        assert "a long page" not in argv and "--" not in argv
        assert argv[:2] == ["/bin/claude", "-p"]

    def test_claude_plan_mode_is_read_only(self):
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt="hi",
            permission_mode="plan",
        )
        assert argv[argv.index("--permission-mode") + 1] == "plan"
        tools = argv[argv.index("--allowedTools") + 1]
        assert "Write" not in tools
        assert "Read" in tools

    def test_claude_bypass_mode(self):
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt="hi",
            permission_mode="bypassPermissions",
        )
        assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
        assert "--dangerously-skip-permissions" in argv

    def test_claude_model_arg_injected(self):
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt="hi", model="opus",
        )
        assert argv.count("--model") == 1
        assert argv[argv.index("--model") + 1] == "opus"


class TestCursorArgv:
    def test_cursor_argv(self):
        argv = build_argv(
            binary="/bin/agent", flavor="cursor", prompt="hi", system_text="sys",
            resume_id="abc", cli_args=["--model", "auto"],
        )
        assert argv[:3] == ["/bin/agent", "-p", "hi"]
        assert "--stream-partial-output" in argv
        assert "--trust" in argv
        assert "--force" in argv
        assert argv[argv.index("--resume") + 1] == "abc"
        assert "--allowedTools" not in argv
        assert argv[-2:] == ["--model", "auto"]

    def test_cursor_plan_omits_force(self):
        argv = build_argv(
            binary="/bin/agent", flavor="cursor", prompt="hi",
            permission_mode="plan",
        )
        assert "--trust" in argv
        assert "--force" not in argv

    def test_cursor_model_arg_injected(self):
        argv = build_argv(
            binary="/bin/agent", flavor="cursor", prompt="hi", model="composer-2.5",
        )
        assert argv.count("--model") == 1
        assert argv[argv.index("--model") + 1] == "composer-2.5"


class TestAntigravityArgv:
    def test_antigravity_argv(self):
        argv = build_argv(
            binary="/bin/agy", flavor="antigravity", prompt="hi there",
            system_text="sys",
        )
        assert argv[:3] == ["/bin/agy", "-p", "hi there"]
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert argv[argv.index("--mode") + 1] == "accept-edits"
        assert "--add-dir" not in argv

    def test_antigravity_attaches_cwd_with_add_dir(self):
        # `agy -p` does not treat subprocess cwd as the workspace.
        argv = build_argv(
            binary="/bin/agy", flavor="antigravity", prompt="hi",
            cwd=r"F:\Code\AgentDesk",
        )
        assert argv[argv.index("--add-dir") + 1] == r"F:\Code\AgentDesk"

    def test_antigravity_passes_model_flag(self):
        argv = build_argv(
            binary="/bin/agy", flavor="antigravity", prompt="hi",
            model="gemini-3.1-pro",
        )
        assert argv[argv.index("--model") + 1] == "gemini-3.1-pro"

    def test_antigravity_resumes_with_conversation(self):
        argv = build_argv(
            binary="/bin/agy", flavor="antigravity", prompt="hi",
            resume_id="78e0306d-c270-4cab-a23a-74f338f1747a",
        )
        assert argv[argv.index("--conversation") + 1] == "78e0306d-c270-4cab-a23a-74f338f1747a"
        assert "--conversation" not in build_argv(
            binary="/bin/agy", flavor="antigravity", prompt="hi"
        )


class TestGeminiArgv:
    def test_gemini_argv(self):
        argv = build_argv(
            binary="/bin/gemini", flavor="gemini", prompt="hi",
            system_text="sys", model="gemini-2.5-flash",
        )
        assert argv[:3] == ["/bin/gemini", "-p", "hi"]
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--skip-trust" in argv
        assert argv[argv.index("--approval-mode") + 1] == "yolo"
        assert argv[argv.index("--model") + 1] == "gemini-2.5-flash"

    def test_gemini_plan_mode_is_read_only(self):
        argv = build_argv(
            binary="/bin/gemini", flavor="gemini", prompt="hi",
            permission_mode="plan",
        )
        assert argv[argv.index("--approval-mode") + 1] == "plan"


class TestCopilotArgv:
    def test_copilot_argv(self):
        argv = build_argv(
            binary="/bin/copilot", flavor="copilot", prompt="hi",
            model="auto", resume_id="abc123",
        )
        assert argv[:3] == ["/bin/copilot", "-p", "hi"]
        assert argv[argv.index("--output-format") + 1] == "json"
        assert "--no-ask-user" in argv
        assert "--resume=abc123" in argv
        # Default headless mode auto-approves tools (required in -p mode).
        assert "--allow-all-tools" in argv
        assert argv[argv.index("--model") + 1] == "auto"

    def test_copilot_plan_mode(self):
        argv = build_argv(
            binary="/bin/copilot", flavor="copilot", prompt="hi",
            permission_mode="plan",
        )
        assert "--plan" in argv
        assert "--allow-all-tools" not in argv


class TestPromptComposition:
    def test_prompt_inlines_system_for_non_claude(self):
        assert compose_prompt("claude", "hi", "sys", None) == "hi"
        assert compose_prompt("cursor", "hi", "sys", None) == "sys\n\nhi"
        assert compose_prompt("cursor", "hi", "sys", "r1") == "hi"
        assert compose_prompt("antigravity", "hi", "", None) == "hi"
        assert compose_prompt("gemini", "hi", "sys", None) == "sys\n\nhi"


class TestModelArgHelper:
    def test_drops_legacy_placeholders(self):
        assert model_args("claude", None) == []
        assert model_args("claude", "") == []
        assert model_args("claude", "default") == []
        assert model_args("claude", "Claude Code") == []
        assert model_args("cursor", "Cursor Agent") == []
        assert model_args("gemini", "Gemini CLI") == []
        assert model_args("antigravity", "default") == []
        assert model_args("claude", "sonnet") == ["--model", "sonnet"]
        assert model_args("gemini", "gemini-2.5-flash") == ["--model", "gemini-2.5-flash"]


class TestCursorTextExtraction:
    def test_cursor_text_extraction(self):
        delta = {
            "type": "assistant",
            "timestamp_ms": 1,
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        assert _extract_cursor_text(delta) == "Hello"
        # Buffered flush (has model_call_id) must be ignored.
        flush = {
            "type": "assistant",
            "timestamp_ms": 1,
            "model_call_id": "x",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        assert _extract_cursor_text(flush) == ""


class TestGrokPermissions:
    """Grok's own modes do not restrict it headless (verified live): the guard is its tool set."""

    def _argv(self, mode):
        return build_argv(binary="grok", flavor="grok", prompt="hi", permission_mode=mode)

    def test_grok_plan_and_ask_are_read_only(self):
        for mode in ("plan", "manual"):
            argv = self._argv(mode)
            tools = set(argv[argv.index("--tools") + 1].split(","))
            assert tools <= {"read_file", "list_dir", "grep", "todo_write", "web_search", "web_fetch"}
            assert argv[argv.index("--deny") + 1] == "MCPTool"
            assert argv[argv.index("--disallowed-tools") + 1] == "Agent"
            assert "--permission-mode" not in argv

    def test_grok_edit_modes_deny_the_shell_and_mcp(self):
        for mode in ("acceptEdits", "dontAsk", None):
            argv = self._argv(mode)
            assert [argv[i + 1] for i, arg in enumerate(argv) if arg == "--deny"] == ["Bash", "MCPTool"]
            assert argv[argv.index("--disallowed-tools") + 1] == "Agent"

    def test_grok_edit_modes_approve_edits_instead_of_cancelling_the_turn(self):
        # grok 1.0.77 `--permission-mode acceptEdits` asks before search_replace; headless,
        # that ask cancels the turn. Only read and edit tools remain, and they are approved.
        for mode in ("acceptEdits", "dontAsk", None):
            argv = self._argv(mode)
            assert "--always-approve" in argv
            assert "--permission-mode" not in argv
            tools = set(argv[argv.index("--tools") + 1].split(","))
            assert {"search_replace", "write"} <= tools
            assert tools <= {
                "read_file", "list_dir", "grep", "todo_write", "web_search", "web_fetch",
                "search_replace", "write",
            }

    def test_grok_bypass_approves_everything(self):
        argv = self._argv("bypassPermissions")
        assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
        assert "--deny" not in argv

    def test_grok_auto_approves_tools_instead_of_waiting_for_a_click(self):
        # `--permission-mode auto` still prompts. Headless, that prompt cancels the turn.
        argv = self._argv("auto")
        assert "--always-approve" in argv
        assert "--permission-mode" not in argv
        assert "--deny" not in argv

    def test_grok_resume_is_passed_as_a_flag(self):
        argv = build_argv(
            binary="grok", flavor="grok", prompt="hi", resume_id="01a0a000-0000-7000-8000-000000000001",
        )
        assert argv[argv.index("--resume") + 1] == "01a0a000-0000-7000-8000-000000000001"

    def test_grok_can_read_its_prompt_from_stdin(self):
        argv = build_argv(binary="grok", flavor="grok", prompt="a long prompt", prompt_on_stdin=True)
        assert argv[argv.index("-p") + 1] == "-"
        assert "a long prompt" not in argv


class TestOpenCodeArgv:
    """OpenCode rejects any tool that would ask for approval: plan uses its read-only agent."""

    def _argv(self, **kwargs):
        return build_argv(binary="opencode", flavor="opencode", prompt="-hi", **kwargs)

    def test_opencode_flavor(self):
        assert flavor_for("opencode") == "opencode"

    def test_opencode_runs_headless_without_a_dir_flag(self):
        # OpenCode 2 rejects `--dir`. The project is the process cwd (and PWD),
        # set by the runner, not an argv flag.
        argv = self._argv(cwd="/code/app", model="openrouter/stealth/union-alpha")
        assert argv[:5] == ["opencode", "run", "--format", "json", "--thinking"]
        assert "--dir" not in argv
        assert "/code/app" not in argv
        assert argv[argv.index("--model") + 1] == "openrouter/stealth/union-alpha"
        # The prompt comes after `--`, so a leading dash is not parsed as a flag.
        assert argv[-2:] == ["--", "-hi"]

    def test_opencode_plan_and_ask_use_the_plan_agent(self):
        for mode in ("plan", "manual"):
            argv = self._argv(permission_mode=mode)
            assert argv[argv.index("--agent") + 1] == "plan"
            assert "--auto" not in argv

    def test_opencode_edit_modes_use_the_build_agent(self):
        for mode in ("acceptEdits", "auto", "dontAsk", None):
            argv = self._argv(permission_mode=mode)
            assert "--agent" not in argv and "--auto" not in argv

    def test_opencode_bypass_auto_approves(self):
        argv = self._argv(permission_mode="bypassPermissions")
        assert "--auto" in argv and "--agent" not in argv

    def test_opencode_resume_is_a_session_flag(self):
        argv = self._argv(resume_id="ses_f504cd75fffehYULWTaZuNfg2b")
        assert argv[argv.index("--session") + 1] == "ses_f504cd75fffehYULWTaZuNfg2b"


class TestAllowedTools:
    """``allowed_tools`` replaces Claude's default ``--allowedTools`` list; other flavors ignore it."""

    @staticmethod
    def _claude(**kwargs):
        return build_argv(binary="claude", flavor="claude", prompt="hi", system_text="sys", **kwargs)

    @staticmethod
    def _rules(argv):
        return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--allowedTools"]

    def test_none_keeps_todays_argv_byte_for_byte(self):
        assert self._claude() == [
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--append-system-prompt", "sys",
            "--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read,Edit,Write",
            "--disallowedTools", ",".join(token_file_denials()), "--", "hi",
        ]
        assert self._claude(allowed_tools=None) == self._claude()
        plan = self._claude(permission_mode="plan", allowed_tools=None)
        assert self._rules(plan) == ["Bash,Read"]

    def test_a_list_replaces_the_default_in_the_same_position(self):
        default = self._claude()
        argv = self._claude(allowed_tools=["Bash(x:*)"])
        assert self._rules(argv) == ["Bash(x:*)"]
        assert "Bash,Read" not in " ".join(argv)
        assert argv.index("--allowedTools") == default.index("--allowedTools")
        assert argv[:-6] == default[:-6] and argv[-4:] == default[-4:]

    def test_several_rules_are_comma_joined_whatever_the_mode(self):
        for mode in ("plan", "manual", "dontAsk", None):
            argv = self._claude(permission_mode=mode, allowed_tools=["Bash(x:*)", "Read"])
            assert self._rules(argv) == ["Bash(x:*),Read"]

    def test_an_empty_list_drops_the_default_allowed_tools(self):
        for mode in ("plan", "dontAsk", None):
            argv = self._claude(permission_mode=mode, allowed_tools=[])
            assert "--allowedTools" not in argv

    def test_live_default_omits_generic_bash(self):
        """A live turn's default list is Read, plus Edit and Write outside plan/manual."""
        assert self._rules(self._claude(live_input=True)) == ["Read,Edit,Write"]
        assert self._rules(self._claude(live_input=True, permission_mode="plan")) == ["Read"]
        assert self._rules(self._claude(live_input=True, permission_mode="manual")) == ["Read"]
        for mode in ("acceptEdits", "auto", "dontAsk", "bypassPermissions"):
            rules = self._rules(self._claude(live_input=True, permission_mode=mode))
            assert rules == ["Read,Edit,Write"]
            assert "Bash" not in rules[0].split(",")
            assert "d3skwebscout" not in rules[0]

    def test_the_live_input_turn_honours_it_too(self):
        argv = self._claude(live_input=True, allowed_tools=["Bash(x:*)"])
        assert self._rules(argv) == ["Bash(x:*)"]
        assert "--allowedTools" not in self._claude(live_input=True, allowed_tools=[])

    def test_cli_args_still_add_rules(self):
        argv = self._claude(allowed_tools=["Bash(x:*)"], cli_args=["--allowedTools", "Bash(y:*)"])
        assert self._rules(argv) == ["Bash(x:*)", "Bash(y:*)"]

    def test_a_rule_with_a_comma_is_refused(self):
        with pytest.raises(ValueError, match="comma"):
            self._claude(allowed_tools=["Bash(a,b:*)"])
        # the rules are joined with commas: it would silently split in two
        with pytest.raises(ValueError):
            self._claude(allowed_tools=["Read", "Bash(a,b:*)"])

    def test_other_flavors_ignore_it(self):
        for flavor in ("cursor", "antigravity", "grok", "opencode", "gemini", "copilot"):
            plain = build_argv(binary="b", flavor=flavor, prompt="hi", permission_mode="dontAsk")
            for tools in (["Bash(x:*)"], []):
                argv = build_argv(
                    binary="b", flavor=flavor, prompt="hi", permission_mode="dontAsk", allowed_tools=tools,
                )
                assert argv == plain, flavor



class TestTokenFileDenials:
    """Every Claude turn denies the bridge home and the gateway's token files."""

    def _denied(self, argv):
        rules = []
        for index, arg in enumerate(argv):
            if arg == "--disallowedTools":
                rules += argv[index + 1].split(",")
        return rules

    @pytest.mark.parametrize("live_input", [False, True])
    @pytest.mark.parametrize("allowed_tools", [None, [], ["Bash"]])
    def test_every_claude_turn_carries_the_deny_rules(self, tmp_path, monkeypatch, live_input, allowed_tools):
        home = tmp_path / "bridge home"
        monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(home))
        argv = build_argv(
            binary="/bin/claude", flavor="claude", prompt="hi", live_input=live_input, allowed_tools=allowed_tools,
        )
        denied = self._denied(argv)
        assert f"Read(/{home.as_posix()}/**)" in denied
        assert f"Bash(*{home.as_posix()}/*)" in denied
        assert "Bash(*gateway-owner-token*)" in denied
        assert "Read(**/gateway-token)" in denied
        if not live_input:
            assert argv[-2:] == ["--", "hi"]  # the variadic flag cannot swallow the prompt

    def test_a_home_under_the_user_home_is_also_denied_in_tilde_form(self, monkeypatch):
        from pathlib import Path

        monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(Path.home() / ".acb-test-home"))
        denied = self._denied(build_argv(binary="/bin/claude", flavor="claude", prompt="hi"))
        assert "Bash(*~/.acb-test-home/*)" in denied

    def test_a_home_spelled_through_home_variables_or_quotes_is_denied(self, monkeypatch):
        import fnmatch
        from pathlib import Path

        monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(Path.home() / ".agent-cli-bridge"))
        denied = self._denied(build_argv(binary="/bin/claude", flavor="claude", prompt="hi"))
        bash = [rule[5:-1] for rule in denied if rule.startswith("Bash(")]
        for command in (
            'cat "$HOME"/.agent-cli-bridge/gateway-own*',
            "cat $HOME/.agent-cli-bridge/gateway-own*",
            "cat ${HOME}/.agent-cli-bridge/g*",
            "ls ~/.agent-cli-bridge",
        ):
            assert any(fnmatch.fnmatchcase(command, pattern) for pattern in bash), command
        assert not any(fnmatch.fnmatchcase("ls ~/.agent-cli-bridge-work/x", pattern) for pattern in bash)

    def test_the_workdir_beside_the_home_is_not_denied(self, tmp_path, monkeypatch):
        home = tmp_path / ".agent-cli-bridge"
        monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(home))
        denied = self._denied(build_argv(binary="/bin/claude", flavor="claude", prompt="hi"))
        command = f"ls {tmp_path.as_posix()}/.agent-cli-bridge-work/x"
        import fnmatch

        bash = [rule[5:-1] for rule in denied if rule.startswith("Bash(")]
        assert not any(fnmatch.fnmatchcase(command, pattern) for pattern in bash)
        assert any(fnmatch.fnmatchcase(f"cat {home.as_posix()}/gateway-token", pattern) for pattern in bash)

    def test_other_flavors_get_no_claude_rules(self):
        for flavor in ("cursor", "antigravity", "grok", "opencode", "gemini", "copilot"):
            argv = build_argv(binary="b", flavor=flavor, prompt="hi")
            assert "--disallowedTools" not in argv, flavor


@pytest.mark.parametrize("flavor", ["claude", "cursor", "gemini", "grok", "opencode", "copilot", "antigravity"])
def test_a_model_id_that_looks_like_a_flag_is_refused(flavor):
    with pytest.raises(ValueError, match="cannot start with '-'"):
        model_args(flavor, "--yolo")
    with pytest.raises(ValueError):
        build_argv(binary="b", flavor=flavor, prompt="hi", model=" -x")
