"""Stdout parsers for the CLI flavors, one module each."""

from .antigravity import parse_stdout as parse_antigravity
from .claude import parse_stdout as parse_claude
from .common import JsonLine, SessionIds, iter_jsonl
from .copilot import parse_stdout as parse_copilot
from .cursor import parse_stdout as parse_cursor
from .gemini import parse_stdout as parse_gemini
from .grok import parse_stdout as parse_grok
from .opencode import parse_stdout as parse_opencode

__all__ = [
    "JsonLine",
    "SessionIds",
    "iter_jsonl",
    "parse_antigravity",
    "parse_claude",
    "parse_copilot",
    "parse_cursor",
    "parse_gemini",
    "parse_grok",
    "parse_opencode",
]
