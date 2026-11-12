"""Grok CLI stdout. The bytes are Claude's stream-json, plus Grok's own cancel note."""

from collections.abc import AsyncIterator
from typing import Any

from ..events import StreamEvent
from .claude import parse_stdout as parse_claude_stdout

CANCELLED_MESSAGE = (
    "Grok cancelled its own turn: a tool needed an approval that a headless run cannot "
    "give. Choose a more permissive mode (e.g. Bypass) if it should run that tool."
)


async def parse_stdout(lines: AsyncIterator[bytes], **kwargs: Any) -> AsyncIterator[StreamEvent]:
    """A headless Grok turn that stops for an approval is reported as cancelled."""
    kwargs["cancelled_message"] = CANCELLED_MESSAGE
    async for event in parse_claude_stdout(lines, **kwargs):
        yield event
