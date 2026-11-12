"""OpenCode ``run --format json`` stdout (captured live 2026-09-17).

Every event carries ``sessionID``. Text and reasoning arrive as whole parts, not deltas.
An error event (bad model, provider refusal) ends the run with exit 1 and no text.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from ..events import StreamError, StreamEvent, TextDelta, ThinkingDelta, ToolCall, ToolResult
from .common import SessionIds, iter_jsonl


def _tool_events(part: dict, started: set[str]) -> list[StreamEvent]:
    """A finished tool part is the call and its result; a part still running is only the call."""
    call_id = str(part.get("callID") or part.get("id") or "")
    state = part.get("state") or {}
    if not isinstance(state, dict):
        return []
    events: list[StreamEvent] = []
    if call_id not in started:
        started.add(call_id)
        events.append(ToolCall(call_id, str(part.get("tool") or "tool"), state.get("input") or {}))
    status = state.get("status")
    if status == "completed":
        output = state.get("output")
        events.append(ToolResult(call_id, output if isinstance(output, str) else "", False))
    elif status == "error":
        error = state.get("error")
        events.append(ToolResult(call_id, error if isinstance(error, str) else "", True))
    return events


def _error_message(event: dict) -> str:
    """``{"type":"error","error":{"name","data":{"message",…}}}`` → the human message."""
    error = event.get("error") or {}
    if not isinstance(error, dict):
        return str(error) or "Open Router reported an error"
    data = error.get("data")
    if isinstance(data, dict) and isinstance(data.get("message"), str) and data["message"]:
        return data["message"]
    name = str(error.get("name") or "Open Router error")
    return f"{name}: {json.dumps(data, ensure_ascii=False)}" if data else name


def _part_events(event: dict, *, activity: bool, seen: Any, started: set[str]) -> list[StreamEvent]:
    etype = event.get("type")
    part = event.get("part") or {}
    if not isinstance(part, dict):
        return []
    if etype == "text":
        text = part.get("text")
        if isinstance(text, str) and text:
            # Separate parts are separate paragraphs (one per step).
            delta = TextDelta(f"\n\n{text}" if seen.yes else text)
            seen.yes = True
            return [delta]
        return []
    if etype == "error":
        seen.yes = True
        return [StreamError(_error_message(event), code="agent_error")]
    if not activity:
        return []
    if etype == "reasoning":
        text = part.get("text")
        if isinstance(text, str) and text:
            return [ThinkingDelta(text)]
        return []
    if etype == "tool_use":
        return _tool_events(part, started)
    return []


async def parse_stdout(
    lines: AsyncIterator[bytes],
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
) -> AsyncIterator[StreamEvent]:
    """OpenCode events: one session id, whole text parts, and tool parts that arrive finished."""
    started: set[str] = set()
    async for item in iter_jsonl(lines):
        if not item.parsed or not isinstance(item.value, dict):
            continue
        event = item.value
        update = sessions.dedupe(event.get("sessionID"), require_str=True)
        if update is not None:
            yield update
        for piece in _part_events(event, activity=activity, seen=seen, started=started):
            yield piece
