"""A composer's Effort and Ultracode reach only the CLIs that take them, as known values."""

import json
import shutil
import subprocess

import pytest

from agent_cli_bridge.effort import claude_effort_levels, effort_args
from agent_cli_bridge.ui_assets import UI_DIR


def test_claude_gets_effort_and_ultracode_flags():
    args = effort_args("claude", "max", True)
    assert args[:2] == ["--effort", "max"]
    assert args[2] == "--settings" and json.loads(args[3]) == {"ultracode": True}


def test_auto_or_missing_values_pass_nothing():
    assert effort_args("claude") == []
    assert effort_args("claude", "auto", False) == []


def test_an_unknown_effort_never_becomes_an_argument():
    # The value goes into argv: anything outside the known levels is dropped, not passed on.
    assert effort_args("claude", "--dangerously-skip-permissions") == []
    assert effort_args("claude", None, "true") == []
    assert effort_args("copilot", "max") == []


def test_copilot_gets_reasoning_effort_only():
    assert effort_args("copilot", "high", True) == ["--reasoning-effort", "high"]


def test_other_clis_get_nothing():
    for flavor in ("cursor", "gemini", "grok", "opencode", "antigravity"):
        assert effort_args(flavor, "high", True) == []


def test_a_claude_model_without_effort_gets_neither_flag():
    assert effort_args("claude", "high", True, "claude-sonnet-4-5-20250929") == []
    assert effort_args("claude", "max", True, "us.anthropic.claude-opus-4-1-v1:0") == []


def test_a_level_the_model_lacks_runs_as_the_strongest_below_it():
    assert effort_args("claude", "max", False, "claude-opus-4-5") == ["--effort", "high"]
    assert effort_args("claude", "xhigh", False, "claude-opus-4-6") == ["--effort", "high"]
    assert effort_args("claude", "max", False, "opus") == ["--effort", "max"]
    assert effort_args("claude", "xhigh", False, "claude-opus-6") == ["--effort", "xhigh"]


def test_ultracode_never_goes_to_haiku():
    assert effort_args("claude", "low", True, "haiku") == ["--effort", "low"]
    assert effort_args("claude", "auto", True, "claude-opus-5-5[1m]")[0] == "--settings"


MODELS = [
    "", "opus", "sonnet", "haiku", "fable", "claude-opus-5-5", "claude-opus-5-5[1m]", "claude-opus-4-7",
    "claude-opus-4-6", "claude-opus-4-5-20251101", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-sonnet-4",
    "claude-opus-4-1@20250805", "claude-haiku-4-5-20251001", "claude-3-7-sonnet", "claude-mythos-5",
    "claude-mythos-5-1", "us.anthropic.claude-opus-4-6-v1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic/claude-opus-4-5", "claude-opus-6",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_table_matches_the_page_one():
    script = (
        f"const M = require({json.dumps(str(UI_DIR / 'models.js'))});"
        f"const out = {{}}; for (const m of {json.dumps(MODELS)}) {{"
        "const p = M.effortProfile('claude', m); out[m] = p ? p.levels : null; }"
        "process.stdout.write(JSON.stringify(out));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    page = json.loads(result.stdout)
    for model in MODELS:
        levels = claude_effort_levels(model)
        assert page[model] == (list(levels) if levels else None), model
