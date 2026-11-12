"""`.github/KNOWLEDGE.md` matches the KNOWLEDGE template shape (AC30)."""

import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / ".github" / "KNOWLEDGE.md"
pytestmark = pytest.mark.skipif(
    not KNOWLEDGE.is_file(),
    reason="KNOWLEDGE.md is synced on this machine and is not in the git checkout",
)

_INTRO = (
    "# KNOWLEDGE BASE — AgentCliBridge\n"
    "\n"
    "Solved problems, workarounds, quirks, and decisions with their why. **Searched with `grep`,\n"
    "never loaded whole** — so every entry title is the exact error text or a greppable phrase.\n"
    "Update an existing entry rather than adding a near-duplicate.\n"
)

_LABELS = ("**Context:**", "**Cause:**", "**Fix:**", "**Why:**")

# Distinctive phrases from the entries that were already in this file. Dropping one means
# an incident was removed; none of these were added by the rewrite.
_KEPT = (
    "ThinkingDelta",
    "stream_event",
    "thinking_delta",
    "interleavedOutput",
    "assistant.reasoning_delta",
    "assistant.message_delta",
    "--include-partial-messages",
    "Terminé.",
    "_AfterResult",
    "background_tasks_changed",
    "local_bash",
    "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0",
    "claude_background_wait",
    "600000",
    'system_text = ""',
    "--append-system-prompt",
    "X-Bridge-Session",
    '"BLUE"',
    '"RED"',
    "compose_prompt",
    "This command requires approval",
    "permission-prompt-tool stdio",
    "updatedPermissions",
    "isReplay",
    "claude exited cleanly with no output",
    '"num_turns":0',
    "test_a_stale_result_before_the_prompt_is_taken_does_not_end_the_turn",
    "test_a_result_still_ends_the_turn_when_claude_never_echoes_the_prompt",
    "accepted for compatibility",
    "read_file,list_dir,grep,todo_write,web_search,web_fetch",
    "Denied by permission policy",
    "PermissionCancelled",
    "Auto mode blocked this action",
    "--always-approve",
    "stealth/union-alpha",
    "chunkTimeout",
    "OPENCODE_CONFIG_CONTENT",
    "120000",
    "SSE read timed out",
    "Unrecognized flag: --dir in command opencode run",
    "opencode_directory",
    "#27392",
    "default-cli-project",
    "--add-dir",
    "unrecognized_model",
    "passthrough is not supported",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
    "models-known.json",
    "claude-opus-5-5[1m]",
    "fetch_json",
    "ProxyOverride",
    "Provider 'custom' is not supported",
    "INJECTION-TEST-HOP-0",
    "WebFetch",
    "merge_settings_args",
    "punctuation_chars",
    "decision_reason_type",
    "Bash(d3skwebscout search:*)",
    "shims.py",
    "WEBSCOUT_",
    "AGENT_CLI_BRIDGE_SECURITY_LOG",
    "injection_detected",
    "flagged_passages",
    "valueFor, not valueOf",
    "command::model",
    "globalThis.AgentModels",
    "catch_up_claude_cask",
    "drill-down",
    "clear_macos_quarantine",
    "read_opencode_catalog",
    "isLocalAgent",
    "ui_assets.UI_DIR",
    "fake-dom.cjs",
    "acb-btn",
    "--settings-pad, 14px 18px",
    "The system cannot find the file specified.",
    "BatBadBut",
    "list2cmdline",
    "CVE-2024-43402",
    "direct_launch",
    "CURSOR_INVOKED_AS",
    "UnsafeLauncherError",
    "_expand",
    "LOCALAPPDATA",
    "Google.AntigravityCLI",
    "CLI agent binary not found on PATH: grok",
    "ERROR_FILENAME_EXCED_RANGE",
    "32,767",
    "STDIN_PROMPT_FLAVORS",
    "prompt_too_long",
    "requires-python >=3.11",
    "python3.13",
    "ACB_UPDATE_STREAMS",
    "tests/streams/capture.py",
    "no Gemini capture yet",
    "glm-5.2-colibri",
    "family_registry.py",
    "CTX=32768",
    "scheduler.active",
    "test_opencode_never_waits_on_the_hosts_open_stdin",
    "16.6k",
    "git subtree",
    "2be5736",
    "available_agents()",
    "agentclibridge",
    "bump_consumers.py",
    "43cf098",
    "ec23f46",
    "82653b3",
    "UV_PROJECT_ENVIRONMENT",
    "installer._installed",
    "wire.to_wire",
    '"v": 1',
    "sse_frame",
    "mountTranscript",
    "3 background agents didn't finish",
)

_CHOICES = (
    "Python ≥ 3.11 stdlib-only core",
    "run_agent(..., activity=True) yields ThinkingDelta, ToolCall, ToolResult",
    "Grok headless: its permission modes do not restrict it",
    "permission_args maps the host's auto to --always-approve",
    "InjectionGuard lives in `run_agent`",
    "corporate endpoint security flags MCP servers",
    "AgentHost (`host.py`) is the one object a host process keeps",
    "apps pin AgentCliBridge by git, never vendor it",
    "scripts/bump_consumers.py ships each push to all",
    "the bridge owns the wire",
    "Why not an OpenCode agent",
)


def _text() -> str:
    return KNOWLEDGE.read_text(encoding="utf-8")


def _unfenced(markdown: str) -> str:
    lines: list[str] = []
    fenced = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return "\n".join(lines)


def _slug(title: str) -> str:
    """GitHub-style anchor: drop punctuation, keep connector chars, spaces to hyphens."""
    kept: list[str] = []
    for char in title.strip().lower():
        if char in " -" or char.isalnum() or unicodedata.category(char).startswith("Pc"):
            kept.append(char)
    return "".join(kept).replace(" ", "-")


def _sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    for line in _unfenced(markdown).splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if current is not None:
                sections.append((current, "\n".join(body)))
            current = line[3:].strip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections.append((current, "\n".join(body)))
    return sections


def _entries(body: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    title: str | None = None
    chunk: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            if title is not None:
                entries.append((title, "\n".join(chunk)))
            title = line[4:].strip()
            chunk = []
        elif title is not None:
            chunk.append(line)
    if title is not None:
        entries.append((title, "\n".join(chunk)))
    return entries


def test_header_matches_the_template() -> None:
    text = _text()
    assert text.startswith(_INTRO)
    assert "BOOTSTRAP_PENDING" not in text
    assert "[PROJECT_NAME]" not in text
    assert "## <Area>" not in _unfenced(text)
    assert "<exact error text, or a greppable title>" not in _unfenced(text)
    assert "How to Use This Knowledge Base" not in text
    assert "Technology Research & Choices" not in text
    assert "📝" not in text


def test_table_of_contents_matches_the_body() -> None:
    sections = _sections(_text())
    names = [name for name, _body in sections]
    assert names[0] == "Table of Contents"
    toc = dict(sections)["Table of Contents"]
    links = []
    for line in toc.splitlines():
        if "](#" not in line:
            continue
        text, _, after = line.partition("](#")
        label = text.split("[", 1)[1]
        anchor = after.split(")", 1)[0]
        links.append((label, anchor))
    body_headings = names[1:]
    assert [label for label, _anchor in links] == body_headings
    assert [anchor for _label, anchor in links] == [_slug(name) for name in body_headings]
    assert "Decisions" in body_headings


def test_no_empty_section_and_every_entry_has_an_area() -> None:
    sections = _sections(_text())
    assert sections
    seen_heading = False
    for name, body in sections:
        assert body.strip(), name
        seen_heading = True
        entries = _entries(body)
        if name == "Table of Contents":
            assert not entries, name
            continue
        assert entries, name
    assert seen_heading
    unfenced = _unfenced(_text())
    assert unfenced.split("## ", 1)[0].find("\n### ") == -1


def test_titles_are_phrases_in_the_entry_and_use_the_four_lines() -> None:
    found = False
    for name, body in _sections(_text()):
        if name == "Table of Contents":
            continue
        for title, entry in _entries(body):
            found = True
            assert title, name
            assert title in entry, title
            positions = [entry.index(label) for label in _LABELS]
            assert positions == sorted(positions), title
    assert found


def test_choices_sit_under_decisions() -> None:
    sections = dict(_sections(_text()))
    decisions = sections["Decisions"]
    titles = [title for title, _entry in _entries(decisions)]
    assert titles == list(_CHOICES)
    for phrase in _CHOICES:
        assert phrase in decisions


def test_recorded_incidents_are_still_there() -> None:
    text = _text()
    missing = [phrase for phrase in _KEPT if phrase not in text]
    assert not missing
