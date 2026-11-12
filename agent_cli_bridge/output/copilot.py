"""GitHub Copilot CLI JSONL (schema captured live 2026-07).

``session.error`` carries the human message. ``result`` carries ``sessionId`` and the
authoritative ``exitCode``: the process itself exits 0 even on failure. Text streams as
``assistant.message_delta`` (``data.deltaContent``); ``assistant.message`` repeats the whole
text and is used only when no delta carried it. ``assistant.reasoning*`` is thinking, never
answer text (verified live 2026-09-13).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..events import StreamEvent, TextDelta, ThinkingDelta, ToolCall, ToolResult
from .common import SessionIds, iter_jsonl, raw_text


@dataclass
class CopilotStatus:
    """Exit code and in-band error the runner reads once the stream ends."""

    result_exit: int | None = None
    pending_error: str | None = None


def _result_text(data: dict) -> tuple[str, bool]:
    is_error = data.get("success") is False
    result = data.get("result")
    if isinstance(result, dict) and isinstance(result.get("content"), str):
        return result["content"], is_error
    error = data.get("error")
    if isinstance(error, dict):
        error = error.get("message")
    return (str(error) if error else ""), is_error


def _result_events(
    event: dict, *, sessions: SessionIds, after_result: Any, status: CopilotStatus
) -> list[StreamEvent]:
    after_result.start()
    if isinstance(event.get("exitCode"), int):
        status.result_exit = event["exitCode"]
    update = sessions.dedupe(event.get("sessionId"))
    return [update] if update is not None else []


def _remember_error(data: Any, status: CopilotStatus) -> None:
    message = data.get("message") if isinstance(data, dict) else None
    status.pending_error = message or status.pending_error or "Copilot CLI reported an error"


def _text_events(etype: str, data: dict, *, seen: Any, streamed: set[Any]) -> list[StreamEvent] | None:
    """Answer text, or None when this event is not an assistant message."""
    if etype == "assistant.message_delta":
        delta = data.get("deltaContent")
        if isinstance(delta, str) and delta:
            streamed.add(data.get("messageId"))
            seen.yes = True
            return [TextDelta(delta)]
        return []
    if etype == "assistant.message":
        content = data.get("content")
        if isinstance(content, str) and content and data.get("messageId") not in streamed:
            seen.yes = True
            return [TextDelta(content)]
        return []
    return None


def _activity_events(etype: str, data: dict) -> list[StreamEvent]:
    if etype == "assistant.reasoning_delta":
        delta = data.get("deltaContent")
        if isinstance(delta, str) and delta:
            return [ThinkingDelta(delta)]
    elif etype == "tool.execution_start":
        return [
            ToolCall(
                str(data.get("toolCallId") or ""),
                str(data.get("toolName") or "tool"),
                data.get("arguments") or {},
            )
        ]
    elif etype == "tool.execution_complete":
        output, is_error = _result_text(data)
        shown = {key: data[key] for key in ("result", "error") if data.get(key) is not None}
        return [ToolResult(str(data.get("toolCallId") or ""), output, is_error, raw=raw_text(shown or None, output))]
    return []


def _line_events(
    event: dict,
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    status: CopilotStatus,
    streamed: set[Any],
) -> list[StreamEvent]:
    etype = event.get("type") or ""
    data = event.get("data") or {}
    if etype == "result":
        return _result_events(event, sessions=sessions, after_result=after_result, status=status)
    if etype == "session.error":
        _remember_error(data, status)
        return []
    if not isinstance(data, dict):
        return []
    text = _text_events(etype, data, seen=seen, streamed=streamed)
    if text is not None:
        return text
    if not activity:
        return []
    return _activity_events(etype, data)


async def parse_stdout(
    lines: AsyncIterator[bytes],
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    status: CopilotStatus,
) -> AsyncIterator[StreamEvent]:
    """Copilot JSONL: deltas, a repeated full message, thinking, and tool calls."""
    streamed: set[Any] = set()
    async for item in iter_jsonl(lines):
        if not item.parsed or not isinstance(item.value, dict):
            continue
        for piece in _line_events(
            item.value,
            activity=activity,
            sessions=sessions,
            seen=seen,
            after_result=after_result,
            status=status,
            streamed=streamed,
        ):
            yield piece
