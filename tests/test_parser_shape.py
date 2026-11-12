"""Each flavor's stdout parser is its own function, and the size limits hold.

Recorded streams stay in ``tests/streams``; this file only checks shape.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "agent_cli_bridge" / "output"
RUNNER = ROOT / "agent_cli_bridge" / "runner.py"
FLAVORS = ("claude", "cursor", "antigravity", "gemini", "grok", "copilot", "opencode")
MAX_FILE_LINES = 800
MAX_FUNCTION_LINES = 80


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_count(path: Path) -> int:
    return len(_text(path).splitlines())


def _functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_text(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_runner_is_at_or_under_800_lines():
    count = _line_count(RUNNER)
    assert count <= MAX_FILE_LINES, f"runner.py is {count} lines"


def test_each_flavor_parser_is_its_own_module():
    runner = _text(RUNNER)
    for flavor in FLAVORS:
        path = OUTPUT / f"{flavor}.py"
        assert path.is_file(), flavor
        count = _line_count(path)
        assert count <= MAX_FILE_LINES, f"{flavor}.py is {count} lines"
        functions = _functions(path)
        parsers = [node for node in functions if node.name == "parse_stdout"]
        assert len(parsers) == 1, flavor
        for node in functions:
            assert node.end_lineno is not None
            length = node.end_lineno - node.lineno + 1
            assert length <= MAX_FUNCTION_LINES, f"{flavor}.{node.name} is {length} lines"
        assert re.search(rf"from \.output\.{flavor} import .*parse_stdout\b", runner), flavor


def test_gemini_and_grok_call_the_shared_parser():
    """The stream-json body stays in one module; Gemini and Grok do not paste it."""
    for flavor in ("gemini", "grok"):
        text = _text(OUTPUT / f"{flavor}.py")
        assert "iter_jsonl" not in text
        assert "parse_claude_stdout" in text
    runner = _text(RUNNER)
    assert "GROK_CANCELLED_MESSAGE" not in runner
    assert "def _copilot_result" not in runner
    assert "def _opencode_tool_events" not in runner
    assert "assistant.message_delta" not in runner
