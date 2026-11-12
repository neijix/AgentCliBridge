"""Upstream chat proxy: the status is known before a 200 stream, and failures are 502."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from gateway_import import require_fastapi

require_fastapi(allow_module_level=True)
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agent_cli_bridge import gateway, upstream  # noqa: E402

BASE = "http://up.test/v1"
CLIENT_TOKEN = "client-token-for-tests"
Handler = Callable[[httpx.Request], httpx.Response]


def _proxy(body: dict, handler: Handler):
    return asyncio.run(upstream.proxy_chat(BASE, body, transport=httpx.MockTransport(handler)))


def _body(response) -> dict:
    return json.loads(response.body)


@pytest.mark.parametrize("status", [400, 429, 500, 503])
@pytest.mark.parametrize("stream", [False, True])
def test_json_error_keeps_upstream_status(status, stream):
    payload = {"error": {"message": "no", "type": "upstream"}}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    response = _proxy({"model": "m", "stream": stream, "messages": []}, handler)
    assert not isinstance(response, StreamingResponse)
    assert response.status_code == status
    assert _body(response) == payload


@pytest.mark.parametrize(
    ("status", "content", "stream"),
    [
        (200, b"not-json", False),
        (404, b"<html>no</html>", True),
        (502, b"\xff", False),
        (500, b"", True),
    ],
)
def test_non_json_body_is_502(status, content, stream):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    response = _proxy({"model": "m", "stream": stream, "messages": []}, handler)
    assert not isinstance(response, StreamingResponse)
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "upstream_bad_response"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("silence"), httpx.HTTPError("boom")],
)
def test_http_error_is_502(stream, exc):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    response = _proxy({"model": "m", "stream": stream, "messages": []}, handler)
    assert not isinstance(response, StreamingResponse)
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "upstream_unreachable"


def test_success_stream_waits_for_the_upstream_status():
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append("upstream")
        sent = json.loads(request.content)
        assert sent["model"] == "local-model"
        assert "bridge" not in sent
        assert str(request.url) == f"{BASE}/chat/completions"
        return httpx.Response(200, content=b"data: hi\n\n")

    async def run():
        response = await upstream.proxy_chat(
            BASE,
            {
                "model": "mlx:local-model",
                "stream": True,
                "bridge": {"cwd": "/tmp"},
                "messages": [{"role": "user", "content": "hi"}],
            },
            transport=httpx.MockTransport(handler),
        )
        order.append("returned")
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
        return response, b"".join(chunks)

    response, raw = asyncio.run(run())
    assert order == ["upstream", "returned"]
    assert isinstance(response, StreamingResponse)
    assert response.status_code == 200
    assert raw == b"data: hi\n\n"


def test_non_stream_json_success_strips_the_prefix():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "chatcmpl"})

    response = _proxy(
        {"model": "mlx:local", "bridge": {"cwd": "/tmp"}, "messages": []},
        handler,
    )
    assert response.status_code == 200
    assert _body(response)["id"] == "chatcmpl"
    assert seen["body"]["model"] == "local"
    assert "bridge" not in seen["body"]


def test_client_timeout_is_finite(monkeypatch):
    seen: dict = {}
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        seen["args"] = args
        seen["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = httpx.MockTransport(lambda _request: httpx.Response(200, json={"id": "ok"}))
        return real(*args, **kwargs)

    monkeypatch.setattr(upstream.httpx, "AsyncClient", factory)
    response = asyncio.run(upstream.proxy_chat(BASE, {"model": "m", "messages": []}))
    timeout = seen["timeout"]
    assert response.status_code == 200
    assert seen["args"] == ()
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 30.0
    assert timeout.read == 300.0
    assert timeout.write is not None
    assert timeout.pool is not None


def test_proxy_source_never_disables_the_timeout():
    root = Path(upstream.__file__).parent
    for name in ("upstream.py", "gateway.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "timeout=None" not in text
        assert "Timeout(None" not in text


def test_route_returns_the_upstream_status_before_streaming(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE}/chat/completions"
        assert json.loads(request.content)["model"] == "bare"
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(upstream.httpx, "AsyncClient", factory)
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_UPSTREAM_OPENAI", BASE)
    client = TestClient(
        gateway.app,
        base_url="http://127.0.0.1:4747",
        headers={"Authorization": f"Bearer {CLIENT_TOKEN}"},
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "mlx:bare",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 429
    assert "text/event-stream" not in response.headers["content-type"]
    assert response.json()["error"]["message"] == "slow down"


def _spy_clients(monkeypatch, handler: Handler) -> list[dict]:
    """Every httpx.AsyncClient the proxy opens, answered by ``handler``; returns their kwargs."""
    opened: list[dict] = []
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        opened.append(dict(kwargs))
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(upstream.httpx, "AsyncClient", factory)
    return opened


def _owner_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_UPSTREAM_OPENAI", BASE)
    return TestClient(
        gateway.app,
        base_url="http://127.0.0.1:4747",
        headers={"Authorization": f"Bearer {CLIENT_TOKEN}"},
    )


def test_the_clients_ignore_proxy_environment_variables(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m1"}]})
        return httpx.Response(200, json={"id": "ok"})

    opened = _spy_clients(monkeypatch, handler)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    client = _owner_client(monkeypatch)
    chat = client.post("/v1/chat/completions", json={"model": "mlx:m1", "messages": []})
    streamed = client.post("/v1/chat/completions", json={"model": "mlx:m1", "stream": True, "messages": []})
    models = client.get("/v1/models")
    status = client.get("/api/status")
    assert [r.status_code for r in (chat, streamed, models, status)] == [200, 200, 200, 200]
    assert len(opened) == 4
    assert all(kwargs.get("trust_env") is False for kwargs in opened), opened


def test_the_callers_authorization_is_not_forwarded_upstream(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "ok", "data": []})

    _spy_clients(monkeypatch, handler)
    client = _owner_client(monkeypatch)
    cookie = {"Cookie": "session=secret", "X-Bridge-Session": "s1"}
    for stream in (False, True):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mlx:m1", "stream": stream, "messages": []},
            headers=cookie,
        )
        assert resp.status_code == 200
    client.get("/v1/models")
    assert len(seen) == 3
    for request in seen:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert CLIENT_TOKEN not in str(request.headers) + request.content.decode()
