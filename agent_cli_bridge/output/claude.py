"""Claude Code's stream-json stdout, which Gemini and Grok still share."""

import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from ..events import (
    ApprovalRequest,
    InputAccepted,
    ModeChanged,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)
from .common import SessionIds, as_object, iter_jsonl, raw_text

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def runs_background_agents(event: dict) -> bool:
    """Whether Claude's ``background_tasks_changed`` lists an agent it still waits for.

    Claude Code ends a turn with a ``result`` while background subagents (or a workflow)
    keep working, then starts a new turn of its own when they report back — stdin closed
    or not. Background shell commands are not counted: Claude does not wait for those.
    """
    tasks = event.get("tasks")
    if not isinstance(tasks, list):
        return False
    return any(
        isinstance(task, dict) and any(kind in str(task.get("task_type") or "") for kind in ("agent", "workflow"))
        for task in tasks
    )


def _result_error_message(event: dict) -> str:
    """Human text of a stream-json ``result`` marked ``is_error`` / ``subtype: error``.

    Claude Code's OAuth expiry is this: no text deltas, then
    ``{"type":"result","subtype":"error","is_error":true,"result":"Failed to authenticate…"}``.
    Treating that ``result`` as a TextDelta made the desk store it as a normal reply.
    """
    result = event.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        for key in ("message", "error", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    errors = event.get("errors")
    if isinstance(errors, list):
        parts = [str(item).strip() for item in errors if str(item).strip()]
        if parts:
            return "\n".join(parts)
    return "The agent reported an error"


def _unwrap_grok_output(text: str) -> str:
    """Grok reports tool results as JSON: ``{"type":"Bash","output":[byte values]}``
    (with terminal colours) or ``{"type":"ReadFile","FileContent":{"content":…}}``."""
    if not text.startswith("{"):
        return text
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    if not isinstance(payload, dict):
        return text
    output = payload.get("output")
    if isinstance(output, list) and all(isinstance(b, int) and 0 <= b < 256 for b in output):
        return _ANSI_ESCAPE.sub("", bytes(output).decode("utf-8", errors="replace"))
    if isinstance(output, str):
        return output
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("content"), str):
            return value["content"]
    return text


def _tool_result_text(content: Any) -> str:
    """Flatten a stream-json tool_result content: a string or a list of text blocks."""
    if isinstance(content, list):
        return "\n".join(
            part.get("text") or ""
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if isinstance(content, str):
        return _unwrap_grok_output(content)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def message_tool_events(event: dict) -> list[StreamEvent]:
    """ToolCall / ToolResult blocks of a Claude-protocol message (Claude Code, Grok)."""
    message = event.get("message") or {}
    blocks = message.get("content") if isinstance(message, dict) else None
    if not isinstance(blocks, list):
        return []
    events: list[StreamEvent] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if event.get("type") == "assistant" and block.get("type") == "tool_use":
            events.append(
                ToolCall(str(block.get("id") or ""), str(block.get("name") or "tool"), block.get("input") or {})
            )
        elif event.get("type") == "user" and block.get("type") == "tool_result":
            content = block.get("content")
            text = _tool_result_text(content)
            raw = raw_text(content, text)
            events.append(
                ToolResult(str(block.get("tool_use_id") or ""), text, bool(block.get("is_error")), raw=raw)
            )
    return events


def _replay_text(event: dict) -> str:
    """The text of a user message Claude Code echoed back (--replay-user-messages)."""
    content = as_object(event.get("message")).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def stream_deltas(event: dict, *, activity: bool, seen: Any) -> list[StreamEvent]:
    """Text and thinking deltas inside one ``stream_event``."""
    delta = as_object(as_object(event.get("event")).get("delta"))
    if delta.get("type") == "text_delta":
        text = delta.get("text") or ""
        if text:
            seen.yes = True
            return [TextDelta(text)]
    elif activity and delta.get("type") == "thinking_delta":
        thinking = delta.get("thinking") or ""
        if thinking:
            return [ThinkingDelta(thinking)]
    return []


def _init_session(event: dict, sessions: SessionIds) -> list[StreamEvent]:
    if event.get("type") != "system" or event.get("subtype") != "init":
        return []
    update = sessions.dedupe(event.get("session_id") or event.get("chat_id"))
    return [update] if update is not None else []


def _is_empty_resume(event: dict, *, live: Any, replays: int, is_failure: bool) -> bool:
    """A resumed session's leftover task, not this turn's result.

    The session first reports a background task its last run left behind, then an empty
    result with ``num_turns`` 0, and only then takes the prompt. Ending the turn on that
    result stopped Claude while it was still answering. Only that exact shape is skipped.
    """
    return bool(
        live is not None
        and replays == 0
        and not is_failure
        and event.get("num_turns") == 0
        and not event.get("result")
    )


def _arm_result_deadline(
    after_result: Any, *, live: Any, has_background_agents: bool, is_live: bool, stdin: Any
) -> None:
    """Close stdin once the live turn has nothing left to say, then start the result grace.

    A message still on its way keeps stdin open, and the CLI answers it next. Background
    subagents still working mean Claude answers again once they report back; that later
    result starts the deadline.
    """
    if live is not None and live._turn_ended() and stdin is not None:
        stdin.close()
    if not has_background_agents and (not is_live or stdin is None or stdin.is_closing()):
        after_result.start()


def stream_json_result(
    event: dict,
    *,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    live: Any,
    replays: int,
    has_background_agents: bool,
    is_live: bool,
    stdin: Any,
    cancel_message: str | None,
) -> Iterator[StreamEvent]:
    """One stream-json ``result``: session id, error or fallback text, then the deadline.

    ``cancel_message`` is set only for Grok, and only when the result says the turn was
    cancelled because a tool wanted an approval a headless run cannot give.
    """
    update = sessions.dedupe(event.get("session_id") or event.get("chat_id"))
    if update is not None:
        yield update
    is_failure = bool(event.get("is_error")) or event.get("subtype") == "error"
    if _is_empty_resume(event, live=live, replays=replays, is_failure=is_failure):
        return
    if is_failure:
        seen.yes = True
        yield StreamError(_result_error_message(event), code="agent_error")
    elif not seen.yes:
        result_text = event.get("result") or ""
        if result_text:
            seen.yes = True
            yield TextDelta(result_text)
    _arm_result_deadline(
        after_result, live=live, has_background_agents=has_background_agents, is_live=is_live, stdin=stdin
    )
    if cancel_message:
        seen.yes = True
        yield StreamError(cancel_message, code="cancelled")


def _control_request(event: dict, *, live: Any, write_stdin: Callable[[dict[str, Any]], bool]) -> list[StreamEvent]:
    request_id = str(event.get("request_id") or "")
    request = as_object(event.get("request"))
    if request.get("subtype") == "can_use_tool":
        tool_input = as_object(request.get("input"))
        live._asked(request_id, tool_input)
        return [
            ApprovalRequest(
                request_id,
                str(request.get("tool_use_id") or ""),
                str(request.get("tool_name") or "tool"),
                tool_input,
                str(request.get("description") or ""),
            )
        ]
    # Nothing else is enabled (no hooks, no SDK MCP servers): refuse rather than leave
    # the CLI waiting for an answer.
    write_stdin({
        "type": "control_response",
        "response": {
            "subtype": "error",
            "request_id": request_id,
            "error": f"Unsupported control request: {request.get('subtype')}",
        },
    })
    return []


def _control_response(event: dict, *, live: Any) -> list[StreamEvent]:
    """The CLI's answer to a TurnInput.set_permission_mode request."""
    response = as_object(event.get("response"))
    asked = live._mode_answered(str(response.get("request_id") or ""))
    if asked is None:
        return []
    if response.get("subtype") == "success":
        granted = as_object(response.get("response")).get("mode")
        return [ModeChanged(str(granted or asked))]
    error = str(response.get("error") or "The CLI refused the mode change.")
    return [ModeChanged(asked, error=error)]


def _live_line(
    event: dict,
    etype: Any,
    *,
    live: Any,
    replays: int,
    write_stdin: Callable[[dict[str, Any]], bool],
) -> tuple[int, list[StreamEvent], bool]:
    """Live control and replayed user messages. The third value is false when this line is not one of those."""
    if etype == "control_request":
        return replays, _control_request(event, live=live, write_stdin=write_stdin), True
    if etype == "control_response":
        return replays, _control_response(event, live=live), True
    if etype == "control_cancel_request":
        live._withdrawn(str(event.get("request_id") or ""))
        return replays, [], True
    if etype == "user" and event.get("isReplay"):
        replays += 1
        if replays > 1:
            live._took_message()
            return replays, [InputAccepted(_replay_text(event))], True
        return replays, [], True
    return replays, [], False


def _before_result(
    event: dict,
    etype: Any,
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    live: Any,
    replays: int,
    has_background_agents: bool,
    write_stdin: Callable[[dict[str, Any]], bool],
) -> tuple[int, bool, list[StreamEvent]]:
    opened = _init_session(event, sessions)
    if opened or (event.get("type") == "system" and event.get("subtype") == "init"):
        return replays, has_background_agents, opened
    if etype == "system" and event.get("subtype") == "background_tasks_changed":
        return replays, runs_background_agents(event), []
    if live is not None:
        replays, pieces, handled = _live_line(event, etype, live=live, replays=replays, write_stdin=write_stdin)
        if handled:
            return replays, has_background_agents, pieces
    if etype == "stream_event":
        return replays, has_background_agents, stream_deltas(event, activity=activity, seen=seen)
    if etype in ("assistant", "user") and activity:
        return replays, has_background_agents, message_tool_events(event)
    return replays, has_background_agents, []


async def parse_stdout(
    lines: AsyncIterator[bytes],
    *,
    activity: bool,
    sessions: SessionIds,
    seen: Any,
    after_result: Any,
    live: Any,
    is_live: bool,
    stdin: Any,
    write_stdin: Callable[[dict[str, Any]], bool],
    cancelled_message: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """Claude Code stream-json. Gemini and Grok still call this with ``live`` left unset.

    ``cancelled_message`` is Grok's note for a result whose ``stop_reason`` is ``cancelled``.
    ``replays`` counts user messages the CLI echoed; the first one is the prompt itself.
    """
    replays = 0
    has_background_agents = False
    async for item in iter_jsonl(lines):
        if not item.parsed or not isinstance(item.value, dict):
            continue
        event = item.value
        if event.get("type") == "result":
            message = cancelled_message if event.get("stop_reason") == "cancelled" else None
            for piece in stream_json_result(
                event,
                sessions=sessions,
                seen=seen,
                after_result=after_result,
                live=live,
                replays=replays,
                has_background_agents=has_background_agents,
                is_live=is_live,
                stdin=stdin,
                cancel_message=message,
            ):
                yield piece
            continue
        replays, has_background_agents, pieces = _before_result(
            event,
            event.get("type"),
            activity=activity,
            sessions=sessions,
            seen=seen,
            live=live,
            replays=replays,
            has_background_agents=has_background_agents,
            write_stdin=write_stdin,
        )
        for piece in pieces:
            yield piece
