"""The OpenAI chat-completions wire of the gateway: messages in, chunks or one body out."""
import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import gateway_sessions
from .events import Completed, SessionUpdate, StreamError, TextDelta

log = logging.getLogger(__name__)


def render_transcript(messages: Any) -> tuple[str, str]:
    """Flatten an OpenAI messages array into (system_text, prompt).

    Single-user-turn conversations pass the message through untouched. Longer
    histories are rendered as a compact transcript so stateless clients still
    get context — CLI ``--resume`` (when a session key is provided) then makes
    this a no-op on later turns because only the latest user message is sent.
    """
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ""
        content = m.get("content")
        if isinstance(content, list):  # OpenAI content-part arrays → text parts
            # Brave Leo sends the page text and the question as separate parts.
            content = "\n\n".join(
                p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
                and p["text"]
            )
        if not isinstance(content, str) or not content:
            continue
        if role in ("system", "developer"):
            system_parts.append(content)
        elif role in ("user", "assistant"):
            turns.append((role, content))
    system_text = "\n\n".join(system_parts)

    if not turns:
        return system_text, ""
    if len(turns) == 1 and turns[0][0] == "user":
        return system_text, turns[0][1]
    lines = ["Conversation so far:"]
    for role, content in turns[:-1]:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    last_role, last_content = turns[-1]
    if last_role == "user":
        lines.append(f"\nReply to the user's latest message:\n{last_content}")
    return system_text, "\n".join(lines)


def _chunk(cid: str, model: str, *, content: str | None = None,
           finish: str | None = None, role: str | None = None) -> str:
    delta: dict[str, Any] = {}
    if role:
        delta["role"] = role
    if content:
        delta["content"] = content
    payload = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _error_json(message: str, code: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": "cli_bridge_error", "code": code}}


def _error_chunk(message: str, code: str) -> str:
    return f"data: {json.dumps(_error_json(message, code))}\n\n"


def _error_text(message: str, code: str) -> str:
    """An error as reply text, for a client that shows only ``choices`` (Brave Leo)."""
    return f"\n\n[AgentCliBridge {code}] {message}"


async def _stream_cli_events(
    cid: str,
    model: str,
    events: AsyncIterator[Any],
    *,
    command: str,
    token: str,
    session_id: str | None,
    is_error_text: bool = False,
) -> AsyncIterator[str]:
    """SSE for one CLI turn. After the opening frame, a raised error is one chunk and the stream ends.

    ``is_error_text`` sends an error as reply text instead of an ``error`` chunk, then ends the
    stream as a normal reply.
    """
    def error(message: str, code: str) -> str:
        if is_error_text:
            return _chunk(cid, model, content=_error_text(message, code))
        return _error_chunk(message, code)

    yield _chunk(cid, model, role="assistant")
    try:
        async for ev in events:
            if isinstance(ev, TextDelta):
                yield _chunk(cid, model, content=ev.text)
            elif isinstance(ev, SessionUpdate):
                gateway_sessions._session_put(command, token, session_id, ev.session_id)
            elif isinstance(ev, StreamError):
                yield error(ev.message, ev.code)
    except Exception as exc:
        # CancelledError is a BaseException, so a client disconnect still propagates.
        log.warning("CLI turn failed after the stream started: %s", exc)
        yield error(str(exc) or exc.__class__.__name__, "cli_agent_failed")
        if not is_error_text:
            return  # an error chunk ends the stream; error text is a reply that ends normally
    yield _chunk(cid, model, finish="stop")
    yield "data: [DONE]\n\n"


async def _json_object(request: Request) -> dict[str, Any] | JSONResponse:
    """The request's JSON object body, else a 400 response."""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(_error_json("Invalid JSON body", "bad_request"), status_code=400)
    return body


def _no_user_message() -> JSONResponse:
    return JSONResponse(
        _error_json("messages must contain at least one user message", "bad_request"),
        status_code=400,
    )


DISCONNECT_POLL_SECONDS = 0.25


async def _until_disconnected(request: Request) -> None:
    """Return once the client has hung up."""
    while not await request.is_disconnected():
        await asyncio.sleep(DISCONNECT_POLL_SECONDS)


async def _collect_turn(
    events: AsyncIterator[Any], *, command: str, token: str, session_id: str | None, is_error_text: bool,
) -> tuple[list[str], StreamError | None, int]:
    """Run a turn to its end: (reply text parts, the error if any, the CLI's return code)."""
    text_parts: list[str] = []
    error: StreamError | None = None
    returncode = 0
    try:
        async for ev in events:
            if isinstance(ev, TextDelta):
                text_parts.append(ev.text)
            elif isinstance(ev, SessionUpdate):
                gateway_sessions._session_put(command, token, session_id, ev.session_id)
            elif isinstance(ev, StreamError):
                error = ev
            elif isinstance(ev, Completed):
                returncode = ev.returncode
    except Exception as exc:
        if not is_error_text:
            raise
        log.warning("CLI turn failed: %s", exc)
        error = StreamError(str(exc) or exc.__class__.__name__, code="cli_agent_failed")
    return text_parts, error, returncode


async def _collect_until_disconnect(
    request: Request, events: AsyncIterator[Any], **kwargs: Any
) -> tuple[list[str], StreamError | None, int] | None:
    """``_collect_turn``, or None when the client hangs up first.

    Cancelling the turn closes ``events``, which kills the CLI's process group.
    """
    turn = asyncio.ensure_future(_collect_turn(events, **kwargs))
    gone = asyncio.ensure_future(_until_disconnected(request))
    try:
        await asyncio.wait({turn, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        gone.cancel()
        if not turn.done():
            turn.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await turn
    return turn.result() if turn.done() and not turn.cancelled() else None


async def _turn_response(
    model: str,
    events: AsyncIterator[Any],
    *,
    request: Request,
    stream: bool,
    command: str,
    token: str,
    session_id: str | None,
    is_error_text: bool = False,
) -> StreamingResponse | JSONResponse | dict[str, Any]:
    """One CLI turn as an OpenAI chat completion: SSE when ``stream``, else one JSON body.

    A client that hangs up before the JSON body is ready ends the turn.
    """
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    if stream:
        return StreamingResponse(
            _stream_cli_events(
                cid, model, events, command=command, token=token, session_id=session_id,
                is_error_text=is_error_text,
            ),
            media_type="text/event-stream",
        )

    collected = await _collect_until_disconnect(
        request, events, command=command, token=token, session_id=session_id,
        is_error_text=is_error_text,
    )
    if collected is None:
        return JSONResponse(_error_json("The client disconnected", "client_disconnected"), status_code=499)
    text_parts, error, returncode = collected
    if error and is_error_text:
        text_parts.append(_error_text(error.message, error.code))
    elif error and not text_parts:
        return JSONResponse(_error_json(error.message, error.code), status_code=502)
    return {
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "bridge": {"returncode": returncode},
    }
