"""A client that hangs up before a non-streamed reply is ready ends the CLI turn."""

import asyncio
import json

import pytest
from gateway_import import require_fastapi

require_fastapi(allow_module_level=True)

from agent_cli_bridge import gateway  # noqa: E402

CLIENT_TOKEN = "client-token-for-tests"
OWNER_TOKEN = "owner-token-for-tests"


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})


async def _post(route: str, *, body: dict, hang_up: asyncio.Event | None) -> list[dict]:
    """Call the ASGI app like a server; ``hang_up`` set → the client disconnects."""
    payload = json.dumps(body).encode()
    sent_body = False
    messages: list[dict] = []

    async def receive() -> dict:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}
        if hang_up is not None:
            await hang_up.wait()
        else:
            await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": route,
        "raw_path": route.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:4747"),
            (b"authorization", f"Bearer {CLIENT_TOKEN}".encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 4747),
    }
    await asyncio.wait_for(gateway.app(scope, receive, send), timeout=10)
    return messages


@pytest.mark.parametrize("route", ["/v1/chat/completions", "/browser/v1/chat/completions"])
def test_a_disconnect_cancels_a_non_streamed_turn(monkeypatch, route):
    events: dict[str, asyncio.Event] = {}
    ended: list[str] = []

    async def slow_turn(command, **kwargs):
        events["started"].set()
        try:
            yield gateway.TextDelta(text="partial")
            await asyncio.sleep(60)
            ended.append("finished")
        finally:
            ended.append("closed")  # run_agent's own cleanup kills the process group here

    async def scenario() -> None:
        events["started"] = asyncio.Event()
        body = {"model": "claude:sonnet", "messages": [{"role": "user", "content": "hi"}]}
        await _post(route, body=body, hang_up=events["started"])

    monkeypatch.setattr(gateway, "run_agent", slow_turn)
    asyncio.run(scenario())
    assert ended == ["closed"]


def test_a_connected_client_still_gets_its_reply(monkeypatch):
    async def quick_turn(command, **kwargs):
        yield gateway.TextDelta(text="done")

    monkeypatch.setattr(gateway, "run_agent", quick_turn)
    body = {"model": "claude:sonnet", "messages": [{"role": "user", "content": "hi"}]}
    messages = asyncio.run(_post("/v1/chat/completions", body=body, hang_up=None))
    start = next(m for m in messages if m["type"] == "http.response.start")
    reply = json.loads(b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))
    assert start["status"] == 200
    assert reply["choices"][0]["message"]["content"] == "done"
