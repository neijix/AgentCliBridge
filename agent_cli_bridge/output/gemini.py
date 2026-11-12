"""Gemini CLI stdout. The bytes are Claude's stream-json, with no cancel note of its own."""

from collections.abc import AsyncIterator
from typing import Any

from ..events import StreamEvent
from .claude import parse_stdout as parse_claude_stdout


async def parse_stdout(lines: AsyncIterator[bytes], **kwargs: Any) -> AsyncIterator[StreamEvent]:
    """Gemini speaks Claude's stream-json and does not add a cancel note."""
    async for event in parse_claude_stdout(lines, **kwargs):
        yield event
