"""``run_agent(..., allowed_tools=)`` reaches ``build_argv`` (and so the CLI's argv)."""
import asyncio

import pytest

from agent_cli_bridge import WebScout, run_agent
from agent_cli_bridge import runner as runner_module
from agent_cli_bridge.events import Completed
from agent_cli_bridge.web_scout import SEARCH_RULE

CLAUDE_STREAM = (
    '{"type":"result","subtype":"success","is_error":false,"result":"ok","session_id":"s1"}\n'
)


@pytest.fixture
def captured(monkeypatch):
    """Every ``build_argv`` call made by the runner: its kwargs and (``"argv"``) the real result."""
    calls: list[dict] = []
    real = runner_module.build_argv

    def spy(**kwargs):
        argv = real(**kwargs)
        calls.append({**kwargs, "argv": argv})
        return argv

    monkeypatch.setattr(runner_module, "build_argv", spy)
    return calls


def _run(binary, **kwargs):
    async def collect():
        return [event async for event in run_agent("claude", prompt="hi", binary=binary, **kwargs)]

    return asyncio.run(asyncio.wait_for(collect(), 15))


@pytest.mark.parametrize("allowed", [["Bash(bianca-library:*)"], [], None])
def test_run_agent_passes_allowed_tools_to_build_argv(fake_cli, captured, allowed):
    events = _run(fake_cli(CLAUDE_STREAM), allowed_tools=allowed, web_scout=False)
    assert any(isinstance(event, Completed) for event in events)
    assert captured and all(call["allowed_tools"] == allowed for call in captured)


def test_allowed_tools_defaults_to_none(fake_cli, captured):
    _run(fake_cli(CLAUDE_STREAM), web_scout=False)
    assert captured and all(call["allowed_tools"] is None for call in captured)


def test_the_scout_rules_are_added_next_to_the_replaced_list(fake_cli, captured):
    _run(fake_cli(CLAUDE_STREAM), allowed_tools=["Bash(x:*)"], web_scout=WebScout(caller="test"))
    argv = captured[0]["argv"]
    assert captured[0]["allowed_tools"] == ["Bash(x:*)"]
    # the scout's rules are a separate repeated flag (cli_args), not merged into the replaced list
    values = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--allowedTools"]
    assert "Bash(x:*)" in values
    assert any(SEARCH_RULE in value.split(",") for value in values)
    assert "Bash,Read,Edit,Write" not in values


def test_a_rule_with_a_comma_fails_the_turn_loudly(fake_cli):
    with pytest.raises(ValueError, match="comma"):
        _run(fake_cli(CLAUDE_STREAM), allowed_tools=["Bash(a,b:*)"], web_scout=False)
