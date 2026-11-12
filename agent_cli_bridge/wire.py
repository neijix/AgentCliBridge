"""The chat wire format: runner events as named frames a page can follow, and the stored message shape.

``to_wire`` turns each event of ``events.py`` into ``(name, data)``; ``sse_frame`` writes that pair as
one Server-Sent-Events frame; ``fold`` accumulates frames into the parts a chat message is stored as.
``ui/stream.js`` is the browser half (SSE parser + the same ``fold``), so a server and its page speak
one format. Stdlib only: no web framework is needed to use it.

Apps may add keys to a frame's data and their own frame names; ``fold`` ignores names it does not
know and keeps the extra keys of tool frames on the stored tool part.
"""
import json
from typing import Any

from .events import (
    ActionBlocked,
    ApprovalRequest,
    Completed,
    InjectionDetected,
    InputAccepted,
    ModeChanged,
    SessionUpdate,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)

WIRE_VERSION = 1
ARGUMENTS_LIMIT = 8 * 1024  # characters of a tool's JSON-encoded arguments kept on the wire

# keys of a tool frame that fold maps itself (or never stores); everything else is an app extra
_TOOL_CALL_OWN_KEYS = frozenset({"v", "type", "done", "call_id", "name", "arguments"})
_TOOL_RESULT_OWN_KEYS = frozenset({"v", "type", "done", "call_id", "output", "is_error"})


def _cap(text: str, limit: int) -> tuple[str, bool]:
    """``text`` cut to its first ``limit`` characters, and whether anything was cut."""
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _bound_arguments(arguments: Any) -> tuple[Any, bool]:
    """Tool arguments made safe for ``json.dumps`` and bounded; the flag says they were cut.

    The value is returned unchanged when it encodes within ``ARGUMENTS_LIMIT`` characters. Otherwise
    it becomes a string (its ``str()`` when not JSON-encodable, else the start of its JSON encoding).
    """
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return _cap(str(arguments), ARGUMENTS_LIMIT)
    if len(encoded) > ARGUMENTS_LIMIT:
        return encoded[:ARGUMENTS_LIMIT], True
    return arguments, False


def to_wire(event: object, *, output_limit: int = 20000) -> tuple[str, dict[str, Any]] | None:
    """``(frame name, data)`` for a runner event, or ``None`` for an object that is not one.

    Every data dict carries ``"v": WIRE_VERSION``. Free-text fields (tool output, approval
    description, injection excerpt, mode error) are cut at ``output_limit`` characters and tool
    arguments at ``ARGUMENTS_LIMIT``; when anything was cut the data gets ``"truncated": True``
    (the key is absent otherwise). ``json.dumps`` always succeeds on the returned data.
    """
    data: dict[str, Any] = {"v": WIRE_VERSION}
    is_truncated = False

    def capped(text: object) -> str:
        nonlocal is_truncated
        value, was_cut = _cap(text if isinstance(text, str) else str(text), output_limit)
        is_truncated = is_truncated or was_cut
        return value

    def bounded(arguments: Any) -> Any:
        nonlocal is_truncated
        value, was_cut = _bound_arguments(arguments)
        is_truncated = is_truncated or was_cut
        return value

    match event:
        case TextDelta(text=text):
            name = "text"
            data["text"] = text
        case ThinkingDelta(text=text):
            name = "thinking"
            data["text"] = text
        case ToolCall(call_id=call_id, name=tool_name, arguments=arguments):
            name = "tool_call"
            data.update(call_id=call_id, name=tool_name, arguments=bounded(arguments))
        case ToolResult(call_id=call_id, output=output, is_error=is_error):
            name = "tool_result"
            data.update(call_id=call_id, output=capped(output), is_error=bool(is_error))
        case ApprovalRequest(request_id=request_id, call_id=call_id, name=tool_name, arguments=arguments, description=description):
            name = "approval_request"
            data.update(
                approval_id=request_id,
                call_id=call_id,
                name=tool_name,
                arguments=bounded(arguments),
                description=capped(description),
            )
        case InjectionDetected(call_id=call_id, tool_name=tool_name, rules=rules, excerpt=excerpt, details_url=details_url):
            name = "injection_detected"
            data.update(
                call_id=call_id, tool_name=tool_name, rules=list(rules), excerpt=capped(excerpt), details_url=details_url
            )
        case ActionBlocked(call_id=call_id, name=tool_name, reason=reason, details_url=details_url):
            name = "action_blocked"
            data.update(call_id=call_id, name=tool_name, reason=reason, details_url=details_url)
        case InputAccepted():
            name = "input_accepted"
        case ModeChanged(mode=mode, error=error):
            name = "permission_mode"
            data["mode"] = mode
            if error:
                data["error"] = capped(error)
        case SessionUpdate(session_id=session_id):
            name = "session"
            data["session_id"] = session_id
        case StreamError(message=message, code=code):
            name = "error"
            data.update(message=message, code=code)
        case Completed(returncode=returncode):
            name = "done"
            data["returncode"] = returncode
        case _:
            return None
    if is_truncated:
        data["truncated"] = True
    return name, data


def sse_frame(name: str, data: dict[str, Any]) -> str:
    """One Server-Sent-Events frame: ``event: <name>`` then ``data: <one-line ASCII JSON>``.

    ``data`` is serialised as it is, so app extra keys pass through. ``ValueError`` when ``name``
    holds a line break (it would end the field and inject another one).
    """
    if "\r" in name or "\n" in name:
        raise ValueError(f"SSE event name must not contain a line break: {name!r}")
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def fold(parts: list[dict[str, Any]], name: str, data: dict[str, Any]) -> None:
    """Fold one frame into ``parts`` (in place): the shape a chat message is stored and rendered as.

    ``text`` / ``thinking`` runs merge into ``{"type", "text"}``. ``tool_call`` appends a tool part
    ``{"type": "tool", "call_id", "name", "arguments", "output": "", "is_error": False, "done": False}``
    and ``tool_result`` completes the latest tool part with the same ``call_id`` (no match: nothing
    happens). The extra keys of those two frames (``approval``, ``truncated``, an app's own flags, …)
    are copied onto the tool part, a result's overriding the call's; ``v`` and the keys already mapped
    are not. Any other frame name is ignored. ``ui/stream.js`` has the identical function.
    """
    if not isinstance(data, dict):
        return
    if name in ("text", "thinking"):
        text = "" if data.get("text") is None else data["text"]
        if parts and parts[-1].get("type") == name:
            parts[-1]["text"] += text
        else:
            parts.append({"type": name, "text": text})
    elif name == "tool_call":
        part: dict[str, Any] = {
            "type": "tool",
            "call_id": data.get("call_id"),
            "name": data.get("name"),
            "arguments": data.get("arguments"),
            "output": "",
            "is_error": False,
            "done": False,
        }
        part.update({key: value for key, value in data.items() if key not in _TOOL_CALL_OWN_KEYS})
        parts.append(part)
    elif name == "tool_result":
        call_id = data.get("call_id")
        for part in reversed(parts):
            if part.get("type") == "tool" and part.get("call_id") == call_id:
                part["output"] = "" if data.get("output") is None else data["output"]
                part["is_error"] = False if data.get("is_error") is None else data["is_error"]
                part["done"] = True
                part.update({key: value for key, value in data.items() if key not in _TOOL_RESULT_OWN_KEYS})
                break
