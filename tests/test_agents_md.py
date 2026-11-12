"""AC28: AGENTS.md differs from the AICodeFactory template only in this project's sections."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _factory() -> Path | None:
    """The AICodeFactory checkout: ``$AI_CODE_ROOT/AICodeFactory``, else ``~/.ai-template-dir``."""
    root = os.environ.get("AI_CODE_ROOT", "").strip()
    if root and (Path(root) / "AICodeFactory").is_dir():
        return Path(root) / "AICodeFactory"
    pointer = Path.home() / ".ai-template-dir"
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text).expanduser()
    return None


_FACTORY = _factory()
TEMPLATE = _FACTORY / "templates" / "AGENTS.md.template" if _FACTORY else Path("/nonexistent")
pytestmark = pytest.mark.skipif(
    not (ROOT / "AGENTS.md").is_file() or not TEMPLATE.is_file(),
    reason="AGENTS.md and its AICodeFactory template are on the owner's machine, not in the checkout",
)

# Bodies that belong to this repo. Every other template section must match once the
# test-tier sentence is put back.
PROJECT_SECTIONS = {
    "## Core rules",
    "## Taste",
    "## Project-specific notes",
}
EXTRA_SECTIONS: set[str] = set()

TEMPLATE_GATE = (
    "The gate stays under ~5 min: while iterating run only the touched\n"
    "   tests; slow ones live behind `./check.sh --full` (CI, end of a feature) — `test-tiers` skill."
)
PROJECT_GATE = (
    "This\n"
    "   repo has no separate slow suite, so `./check.sh` and `./check.sh --full` are the same gate\n"
    "   — `test-tiers` skill."
)

HEADER_LINES = ("# AGENTS.md — ", "**PROJECT TYPE**:", "**PRIMARY LANGUAGE**:", "**FRAMEWORK**:")
CLIS = (
    "Claude Code",
    "Cursor Agent",
    "Gemini CLI",
    "Antigravity",
    "Grok",
    "Copilot",
    "OpenCode",
)


def _split(text: str) -> tuple[str, dict[str, str]]:
    matches = list(re.finditer(r"(?m)^## .+$", text))
    preamble = text[: matches[0].start()] if matches else text
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(0)] = text[start:end]
    return preamble, sections


def _mask_header(preamble: str) -> str:
    """Drop the template's bootstrap marker and the four filled header lines."""
    text = preamble.replace("<!-- BOOTSTRAP_PENDING -->\n", "")
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(HEADER_LINES):
            kept.append("HEADER\n")
        else:
            kept.append(line)
    return "".join(kept)


def _agents() -> tuple[str, str, dict[str, str]]:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    preamble, sections = _split(text)
    return text, preamble, sections


def _template() -> tuple[str, str, dict[str, str]]:
    text = TEMPLATE.read_text(encoding="utf-8")
    preamble, sections = _split(text)
    return text, preamble, sections


def test_diff_shows_only_this_projects_sections():
    agents, agents_preamble, agents_sections = _agents()
    template, template_preamble, template_sections = _template()
    assert "<!-- BOOTSTRAP_PENDING -->" not in agents
    assert "[PROJECT_NAME]" not in agents
    assert _mask_header(agents_preamble) == _mask_header(template_preamble)
    assert TEMPLATE_GATE in template
    assert PROJECT_GATE in agents
    restored = {
        heading: (body.replace(PROJECT_GATE, TEMPLATE_GATE) if PROJECT_GATE in body else body)
        for heading, body in agents_sections.items()
    }
    differing = sorted(heading for heading, body in template_sections.items() if restored[heading] != body)
    assert differing == sorted(PROJECT_SECTIONS - EXTRA_SECTIONS)
    assert set(agents_sections) - set(template_sections) == EXTRA_SECTIONS
    assert set(template_sections) <= set(agents_sections)


def test_header_names_all_seven_clis():
    _, preamble, _ = _agents()
    type_line = next(line for line in preamble.splitlines() if line.startswith("**PROJECT TYPE**:"))
    for name in CLIS:
        assert name in type_line


def test_session_start_step_3_matches_the_template():
    _, _, agents_sections = _agents()
    _, _, template_sections = _template()
    heading = "## Session start (do this first, ~10s)"
    assert agents_sections[heading] == template_sections[heading]
    assert "3. Read `.github/PROJECT_STATE.md`" in agents_sections[heading]


def test_checklist_keeps_code_health_and_states_one_gate():
    _, _, sections = _agents()
    checklist = sections["## Post-task checklist — checkpoint policy (every response, no exceptions)"]
    assert "`code-health` skill" in checklist
    assert "`test-tiers` skill" in checklist
    assert "no separate slow suite" in checklist
    assert "`./check.sh` and `./check.sh --full` are the same gate" in checklist
    assert "No AI attribution line (`Co-Authored-By`, `Generated with …`)" in checklist
    assert checklist.count(PROJECT_GATE) == 1


def test_core_rules_restore_localhost_and_portability():
    _, _, sections = _agents()
    rules = sections["## Core rules"]
    assert "Localhost is not a trust boundary" in rules
    assert "127.0.0.1" in rules
    assert "a blocking review finding" in rules
    assert "**Portable**:" in rules
    assert "someone else clones it and installs it from the README alone" in rules
    assert "`portable-project` skill" in rules


def test_project_sections_keep_taste_gateway_consumers_and_live_bash():
    _, _, sections = _agents()
    taste = sections["## Taste"]
    notes = sections["## Project-specific notes"]
    assert "Commit subjects say what a user or host now sees" in taste
    assert "scoped under `.acb-ui`" in taste
    assert "Launch tools by full path" in taste
    assert "excluded per clone (`.git/info/exclude`)" in notes
    assert "listens on loopback only" in notes
    assert "never bind it beyond 127.0.0.1" in notes
    assert "python scripts/bump_consumers.py" in notes
    assert "default Claude tool list omits generic Bash and scout Bash rules" in notes
    assert "allows generic Bash, search, status, and a plain fetch only while the turn is clean" in notes
    assert "yields `--allow-risky` to the host until the turn is tainted" in notes
    assert "denies `--allow-risky` outright (`RISKY_FETCH_DENIALS`)" in notes
