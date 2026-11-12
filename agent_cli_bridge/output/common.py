"""One JSONL reader and one session-id dedupe for the CLI stdout parsers."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..events import SessionUpdate


def raw_text(value: Any, kept: str) -> str:
    """The CLI's whole tool result as text when the parser kept less of it; "" when it kept it all.

    InjectionGuard scans this too (``ToolResult.raw``): a field the parser does not show is
    still text the model read.
    """
    if value is None:
        return ""
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return "" if raw == kept else raw


@dataclass(frozen=True)
class JsonLine:
    """One non-empty stdout line, and the JSON value it held when it parsed.

    ``parsed`` is false when the line is not JSON. JSON ``null`` does parse:
    ``parsed`` is true and ``value`` is None, so a caller must not treat None
    as "not JSON". Antigravity shows a non-object line as text; the other
    parsers skip a line that did not parse.
    """

    text: str
    value: Any
    parsed: bool


async def iter_jsonl(lines: AsyncIterator[bytes]) -> AsyncIterator[JsonLine]:
    """Decode each non-empty line from ``lines`` and parse it as one JSON value.

    ``lines`` is the newline-terminated chunks ``_iter_lines`` already yields.
    A line that is not JSON comes back with ``parsed`` false instead of raising,
    which is what every parser used to do in its own ``except JSONDecodeError``.
    """
    async for raw in lines:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            yield JsonLine(text, json.loads(text), True)
        except json.JSONDecodeError:
            yield JsonLine(text, None, False)


def as_object(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else ``{}``: a CLI line may carry any JSON value."""
    return value if isinstance(value, dict) else {}


class SessionIds:
    """The session id already emitted, so a repeat of it is not a second event."""

    def __init__(self) -> None:
        self._seen: Any = None

    def dedupe(self, sid: Any, *, require_str: bool = False) -> SessionUpdate | None:
        """A SessionUpdate for a new id, or None when ``sid`` is empty or already emitted.

        OpenCode only treats a string ``sessionID`` as an id (``require_str``).
        The other CLIs emit whatever truthy id they sent.
        """
        if require_str and not isinstance(sid, str):
            return None
        if not sid or sid == self._seen:
            return None
        self._seen = sid
        return SessionUpdate(sid)
