"""The project-state index stays short. Detail lives in docs/state/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".github" / "PROJECT_STATE.md"
pytestmark = pytest.mark.skipif(
    not STATE.is_file(),
    reason="PROJECT_STATE.md is synced on this machine and is not in the git checkout",
)
ARCHITECTURE = ROOT / "docs" / "state" / "architecture.md"

# AC29: every name the index lists, each still read by the library or a start script.
ENV_NAMES = frozenset({
    "PORT",
    "BRIDGE_UPSTREAM_OPENAI",
    "BRIDGE_PERMISSION_MODE",
    "BRIDGE_WORKDIR",
    "BRIDGE_WEB_SCOUT",
    "AGENT_CLI_BRIDGE_HOME",
    "D3SKWEBSCOUT_DIR",
    "AI_CODE_ROOT",
    "COLI_SETUP_HOME",
    "BRIDGE_TOKEN",
    "BRIDGE_OWNER_TOKEN",
    "AGENT_CLI_BRIDGE_SECURITY_LOG",
    "AGENT_CLI_BRIDGE_URL",
    "AGENT_CLI_BRIDGE_CONFIG_LOCAL",
    "AGENT_CLI_BRIDGE_SHIM_DIR",
    "AGENT_CLI_BRIDGE_INSTALL_DIR",
    "APPS_CONFIG_DIR",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "LOCALAPPDATA",
    "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS",
})

FLAVORS = ("claude", "cursor", "antigravity", "gemini", "grok", "copilot", "opencode")

DETAIL = (
    "docs/state/architecture.md",
    "docs/state/gateway.md",
    "docs/state/agents.md",
    "docs/state/consumers.md",
    "docs/state/packaging.md",
    "docs/state/limitations.md",
)


def _text() -> str:
    return STATE.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _env_names(section: str) -> set[str]:
    names = set()
    for line in section.splitlines():
        if line.startswith("| `"):
            names.add(line.split("`", 2)[1])
    return names


def _library_and_start_scripts() -> str:
    parts = [path.read_text(encoding="utf-8") for path in (ROOT / "agent_cli_bridge").rglob("*.py")]
    for name in ("start.sh", "start.ps1", "start.command"):
        parts.append((ROOT / name).read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_index_is_about_eighty_lines_and_under_8kb():
    text = _text()
    lines = text.splitlines()
    assert 70 <= len(lines) <= 88, len(lines)
    assert STATE.stat().st_size < 8 * 1024


def test_audience_and_seven_clis():
    text = _text()
    assert "anyone can clone and run the library and its tests" in text
    assert "the gateway is loopback-only personal use" in text
    header = _section(text, "## What This Is").lower()
    for flavor in FLAVORS:
        assert flavor in header


def test_env_section_names_only_variables_the_code_reads():
    section = _section(_text(), "## Environment Variables")
    documented = _env_names(section)
    assert documented == ENV_NAMES
    source = _library_and_start_scripts()
    missing = sorted(name for name in documented if name not in source)
    assert missing == []


def test_plan_mode_is_not_called_a_guaranteed_sandbox():
    folded = re.sub(r"\s+", " ", _text().lower())
    assert "sandbox" not in folded
    assert "guaranteed read-only" not in folded
    assert "read-only sandbox" not in folded


def test_key_commands_include_check_start_and_stop():
    commands = _section(_text(), "## Key Commands")
    assert "./check.sh" in commands
    assert "./check.sh --full" in commands
    assert "./start.sh" in commands
    assert "./stop.sh" in commands


def test_omitted_allowed_tools_uses_live_and_non_live_defaults():
    text = _text()
    assert "Bash,Read[,Edit,Write]" not in text
    assert "Omitted on a live turn" in text
    assert "`Read`" in text
    assert "no generic `Bash`" in text
    assert "Bash(d3skwebscout" in text
    assert re.search(r"`Bash,Read`(?!,)", text)
    assert "`Bash,Read,Edit,Write`" in text
    for path in DETAIL:
        assert path in text
        assert (ROOT / path).is_file()


def test_architecture_records_live_approval_rules():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "is_injection" in text
    assert "one HIGH finding, or two different LOW rules" in text
    assert "does not yield" in text and "`ApprovalRequest`" in text
    assert "generic Bash" in text
    assert "d3skwebscout search" in text
    assert "d3skwebscout status" in text
    assert "is_scout_fetch_approval" in text
    assert "--allow-risky" in text
    assert "Edit or Write when they ask" in text
    assert "`InjectionGuard.review`" in text
    assert "`ActionBlocked`" in text
    assert "`DEFAULT_SAFE_TOOLS`" in text
    assert "including `[]`" in text
