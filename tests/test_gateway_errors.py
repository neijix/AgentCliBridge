"""Gateway errors: a bad JSON body, a turn that dies after the stream starts, and a .env newline."""

import json

import pytest
from gateway_import import require_fastapi

require_fastapi(allow_module_level=True)
from fastapi.testclient import TestClient  # noqa: E402

from agent_cli_bridge import gateway  # noqa: E402

CLIENT_TOKEN = "client-token-for-tests"
OWNER_TOKEN = "owner-token-for-tests"


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})


def _client(token: str | None = OWNER_TOKEN) -> TestClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(gateway.app, base_url="http://127.0.0.1:4747", headers=headers)


def test_persist_newline_is_400_and_does_not_write(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    original = "BRIDGE_WORKDIR=/keep\n# comment\nOTHER=1\n"
    env_file.write_text(original)
    resp = _client().post(
        "/api/config",
        json={
            "workdir": "/inside\nEVIL=1",
            "upstream": "http://127.0.0.1:9/v1",
            "persist": True,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "bad_request"
    assert "newline" in body["error"]["message"]
    assert env_file.read_text() == original
    assert gateway._RUNTIME_CONFIG == {}


@pytest.mark.parametrize("value", ["one\ntwo", "one\rtwo", "one\r\ntwo"])
def test_persist_newline_rejected_by_persist_env_does_not_create_file(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="newline"):
        gateway._persist_env({"BRIDGE_WORKDIR": value})
    assert not (tmp_path / ".env").exists()


def test_persist_newline_absent_values_still_merge(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "new"
    env_file = tmp_path / ".env"
    env_file.write_text("BRIDGE_WORKDIR=/old\n# keep\nUNRELATED=yes\n")
    resp = _client().post(
        "/api/config",
        json={
            "workdir": str(workdir),
            "upstream": "http://127.0.0.1:9/v1",
            "permission_mode": "plan",
            "persist": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert env_file.read_text() == (
        f"BRIDGE_WORKDIR={workdir}\n"
        "# keep\n"
        "UNRELATED=yes\n"
        "BRIDGE_PERMISSION_MODE=plan\n"
        "BRIDGE_UPSTREAM_OPENAI=http://127.0.0.1:9/v1\n"
    )
    assert gateway._RUNTIME_CONFIG["workdir"] == str(workdir)
    assert gateway._RUNTIME_CONFIG["upstream"] == "http://127.0.0.1:9/v1"
    assert gateway._RUNTIME_CONFIG["permission_mode"] == "plan"


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/api/config"])
@pytest.mark.parametrize("raw", [b"", b"{", b"not-json", b'{"a":', b"\xff"])
def test_malformed_json_body_is_400(path, raw):
    resp = _client().post(path, content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["type"] == "cli_bridge_error"
    assert "JSON" in body["error"]["message"]


@pytest.mark.parametrize("body", [[1, 2], "text", 3])
def test_a_json_body_that_is_not_an_object_is_400(body):
    resp = _client().post("/v1/chat/completions", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "bad_request"


def _sse_frames(body: str) -> list[str]:
    return [block.strip() for block in body.split("\n\n") if block.strip()]


def _chat(stream: bool, **bridge: object):
    payload: dict[str, object] = {
        "model": "claude:sonnet",
        "stream": stream,
        "messages": [{"role": "user", "content": "hi"}],
    }
    if bridge:
        payload["bridge"] = bridge
    return _client().post("/v1/chat/completions", json=payload)


@pytest.mark.parametrize("text", [None, "hel"])
def test_run_agent_raise_after_stream_started_emits_error_chunk_and_ends(monkeypatch, text):
    async def fake_run_agent(command, **kwargs):
        if text is not None:
            yield gateway.TextDelta(text=text)
        raise RuntimeError("disk full")

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
    resp = _chat(stream=True)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(resp.text)
    if text is not None:
        assert any('"content": "hel"' in frame for frame in frames)
    error = json.loads(frames[-1].removeprefix("data: "))
    assert error == {
        "error": {
            "message": "disk full",
            "type": "cli_bridge_error",
            "code": "cli_agent_failed",
        }
    }
    assert "data: [DONE]" not in resp.text
    assert '"finish_reason": "stop"' not in resp.text


def test_streamed_turn_still_ends_when_the_cli_finishes(monkeypatch):
    async def fake_run_agent(command, **kwargs):
        yield gateway.TextDelta(text="ok")

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
    resp = _chat(stream=True)
    assert resp.status_code == 200, resp.text
    assert resp.text.rstrip().endswith("data: [DONE]")
    assert '"finish_reason": "stop"' in resp.text


def test_stream_error_event_is_a_chunk_and_the_stream_still_closes(monkeypatch):
    async def fake_run_agent(command, **kwargs):
        yield gateway.StreamError(message="nope", code="cli_agent_failed")

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
    resp = _chat(stream=True)
    assert resp.status_code == 200, resp.text
    frames = _sse_frames(resp.text)
    error = json.loads(next(frame.removeprefix("data: ") for frame in frames if '"error"' in frame))
    assert error["error"]["message"] == "nope"
    assert error["error"]["code"] == "cli_agent_failed"
    assert resp.text.rstrip().endswith("data: [DONE]")


@pytest.mark.parametrize("body", [[1, 2], "text", 3, None])
def test_a_config_body_that_is_not_an_object_is_400(body):
    resp = _client().post("/api/config", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "bad_request"
    assert gateway._RUNTIME_CONFIG == {}
