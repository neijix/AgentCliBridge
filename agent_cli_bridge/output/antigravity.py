"""Antigravity's event stdout: prose lines, step updates, and a conversation id."""

from collections.abc import AsyncIterator
from typing import Any

from ..events import StreamEvent, TextDelta, ToolCall, ToolResult
from .common import SessionIds, as_object, iter_jsonl

# Tool step states that end a tool (live captures show DONE; the others are
# defensive guesses so a failed tool is not left "running").
_TOOL_END_STATES = frozenset({"DONE", "ERROR", "FAILED", "CANCELED", "CANCELLED"})


def tool_events(step: dict, started: set[str], finished: set[str]) -> list[StreamEvent]:
    """Antigravity repeats a tool step as its state changes (ACTIVE → DONE)."""
    call_id = str(step.get("step_index"))
    info = as_object(step.get("tool_info"))
    events: list[StreamEvent] = []
    if call_id not in started:
        started.add(call_id)
        name = str(step.get("tool_name") or info.get("name") or "tool")
        events.append(ToolCall(call_id, name, info.get("parameters") or {}))
    state = step.get("state")
    if state in _TOOL_END_STATES and call_id not in finished:
        finished.add(call_id)
        output = info.get("output")
        events.append(ToolResult(call_id, output if isinstance(output, str) else "", state != "DONE"))
    return events


def _step_events(
    event: dict, *, activity: bool, seen: Any, started: set[str], finished: set[str]
) -> list[StreamEvent]:
    step = as_object(event.get("step_update"))
    if step.get("step_type") == "agent_response":
        delta = step.get("text_delta")
        if delta:
            seen.yes = True
            return [TextDelta(delta)]
        return []
    if activity and step.get("step_type") == "tool":
        return tool_events(step, started, finished)
    return []


def _conversation(event: dict, sessions: SessionIds) -> list[StreamEvent]:
    kind = event.get("event")
    if kind == "init":
        update = sessions.dedupe(event.get("conversation_id"))
    elif kind == "result":
        update = sessions.dedupe(as_object(event.get("result")).get("conversation_id"))
    else:
        return []
    return [update] if update is not None else []


async def parse_stdout(
    lines: AsyncIterator[bytes],
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
) -> AsyncIterator[StreamEvent]:
    """Antigravity stdout. A line that is not a JSON object is prose.

    ``{`` is the only prefix ``json.loads`` can turn into an object, so a parsed
    non-object stays text.
    """
    started: set[str] = set()
    finished: set[str] = set()
    async for item in iter_jsonl(lines):
        if not item.parsed or not item.text.startswith("{"):
            seen.yes = True
            yield TextDelta(item.text + "\n")
            continue
        event = item.value
        kind = event.get("event")
        if kind == "step_update":
            for piece in _step_events(event, activity=activity, seen=seen, started=started, finished=finished):
                yield piece
        elif kind in ("init", "result"):
            if kind == "result":
                after_result.start()
            for piece in _conversation(event, sessions):
                yield piece
