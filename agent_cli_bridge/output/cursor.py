"""Cursor Agent's stream-json stdout."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from ..events import StreamEvent, TextDelta, ThinkingDelta, ToolCall, ToolResult
from .claude import runs_background_agents, stream_json_result
from .common import SessionIds, iter_jsonl, raw_text


def extract_cursor_text(event: dict) -> str:
    """Extract streaming text from a Cursor Agent stream-json assistant event.

    Real-time deltas carry timestamp_ms and omit model_call_id; buffered
    flushes before tool calls / end-of-turn are skipped to avoid duplicating
    text (cursor.com/docs/cli/headless).
    """
    if not event.get("timestamp_ms") or event.get("model_call_id"):
        return ""
    message = event.get("message") or {}
    parts = message.get("content") if isinstance(message, dict) else None
    if not isinstance(parts, list) or not parts:
        return ""
    first = parts[0]
    if isinstance(first, dict):
        return first.get("text") or ""
    return ""


def _scalar_arguments(args: Any) -> Any:
    """Cursor attaches parser internals (parsingResult, …) to tool args: keep plain values."""
    if not isinstance(args, dict):
        return args or {}
    return {
        key: value
        for key, value in args.items()
        if isinstance(value, (str, int, float, bool)) and value != "" and key != "toolCallId"
    }


def _cursor_result(result: Any) -> tuple[str, bool]:
    """Cursor tool results are ``{"success": {...}}`` or an error-like key."""
    if not isinstance(result, dict):
        return "", False
    for key, body in result.items():
        is_error = key != "success"
        if isinstance(body, str):
            return body, is_error
        if isinstance(body, dict):
            for field in ("interleavedOutput", "stdout", "content", "output", "error", "message"):
                value = body.get(field)
                if isinstance(value, str) and value:
                    return value, is_error
            return json.dumps(body, ensure_ascii=False), is_error
    return "", False


def cursor_activity(event: dict) -> list[StreamEvent]:
    """ThinkingDelta / ToolCall / ToolResult from Cursor Agent ``thinking`` and ``tool_call`` events."""
    if event.get("type") == "thinking":
        text = event.get("text") if event.get("subtype") == "delta" else None
        return [ThinkingDelta(text)] if isinstance(text, str) and text else []
    call = event.get("tool_call") or {}
    if not isinstance(call, dict):
        return []
    call_id = str(event.get("call_id") or call.get("toolCallId") or "")
    for key, body in call.items():
        if not (key.endswith("ToolCall") and isinstance(body, dict)):
            continue
        name = key[: -len("ToolCall")] or "tool"
        if event.get("subtype") == "started":
            return [ToolCall(call_id, name, _scalar_arguments(body.get("args")))]
        if event.get("subtype") == "completed":
            output, is_error = _cursor_result(body.get("result"))
            return [ToolResult(call_id, output, is_error, raw=raw_text(body.get("result"), output))]
    return []


def _cursor_line(
    event: dict, *, activity: bool, sessions: SessionIds, seen: Any, has_background_agents: bool
) -> tuple[bool, list[StreamEvent]]:
    etype = event.get("type")
    if etype == "system" and event.get("subtype") == "init":
        update = sessions.dedupe(event.get("session_id") or event.get("chat_id"))
        return has_background_agents, [update] if update is not None else []
    if etype == "system" and event.get("subtype") == "background_tasks_changed":
        return runs_background_agents(event), []
    if etype == "assistant":
        text = extract_cursor_text(event)
        if text:
            seen.yes = True
            return has_background_agents, [TextDelta(text)]
        return has_background_agents, []
    if activity and etype in ("thinking", "tool_call"):
        return has_background_agents, cursor_activity(event)
    return has_background_agents, []


def _result_events(
    event: dict,
    *,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    has_background_agents: bool,
    stdin: Any,
) -> Iterator[StreamEvent]:
    yield from stream_json_result(
        event,
        sessions=sessions,
        seen=seen,
        after_result=after_result,
        live=None,
        replays=0,
        has_background_agents=has_background_agents,
        is_live=False,
        stdin=stdin,
        cancel_message=None,
    )


async def parse_stdout(
    lines: AsyncIterator[bytes],
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    stdin: Any,
) -> AsyncIterator[StreamEvent]:
    """Cursor Agent stream-json: assistant text, thinking, tool calls, and the result."""
    has_background_agents = False
    async for item in iter_jsonl(lines):
        if not item.parsed or not isinstance(item.value, dict):
            continue
        event = item.value
        if event.get("type") == "result":
            for piece in _result_events(
                event,
                sessions=sessions,
                seen=seen,
                after_result=after_result,
                has_background_agents=has_background_agents,
                stdin=stdin,
            ):
                yield piece
            continue
        has_background_agents, pieces = _cursor_line(
            event,
            activity=activity,
            sessions=sessions,
            seen=seen,
            has_background_agents=has_background_agents,
        )
        for piece in pieces:
            yield piece
