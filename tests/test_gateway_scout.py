"""Gateway turns: BRIDGE_WEB_SCOUT can disable WebScout; a missing checkout logs once."""

import logging
from pathlib import Path

import pytest
from gateway_import import require_fastapi

require_fastapi(allow_module_level=True)
from fastapi.testclient import TestClient  # noqa: E402

from agent_cli_bridge import gateway  # noqa: E402
from agent_cli_bridge.web_scout import (  # noqa: E402
    FETCH,
    FETCH_RULE,
    SEARCH,
    SEARCH_RULE,
    WebScout,
    venv_python,
)

OWNER_TOKEN = "owner-token-for-tests"
_GATEWAY_OFF = ("0", "off", "false", "OFF", "False", "FALSE", "Off", "  FaLsE  ")
_NO_WEB_TOOLS = ["--disallowedTools", f"WebSearch,WebFetch,{SEARCH},{FETCH},{SEARCH_RULE},{FETCH_RULE}"]
_MISSING_CHECKOUT = "web scout: checkout missing; this turn has no web tools"


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TOKEN", "client-token-for-tests")
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.delenv("BRIDGE_WEB_SCOUT", raising=False)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})


def _client() -> TestClient:
    return TestClient(
        gateway.app,
        base_url="http://127.0.0.1:4747",
        headers={"Authorization": f"Bearer {OWNER_TOKEN}"},
    )


def _checkout(base: Path) -> Path:
    checkout = base / "D3SKWEBSCOUT"
    python = venv_python(checkout)
    python.parent.mkdir(parents=True)
    python.write_text("")
    (checkout / "src" / "d3skwebscout").mkdir(parents=True)
    return checkout


def _capture(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_run_agent(command, **kwargs):
        seen["command"] = command
        seen["web_scout"] = kwargs["web_scout"]
        yield gateway.TextDelta(text="done")
        yield gateway.Completed(0)

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
    return seen


def _post(*, stream: bool = False):
    return _client().post(
        "/v1/chat/completions",
        json={
            "model": "claude:sonnet",
            "stream": stream,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )


def _scout_logs(caplog):
    return [record for record in caplog.records if record.name == "agent_cli_bridge.web_scout"]


def _completed(resp, *, stream: bool):
    assert resp.status_code == 200, resp.text
    if stream:
        assert '"content": "done"' in resp.text
        assert resp.text.rstrip().endswith("data: [DONE]")
        assert '"code": "cli_agent_failed"' not in resp.text
        return
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "done"
    assert body["bridge"]["returncode"] == 0


@pytest.mark.parametrize("switch", _GATEWAY_OFF)
@pytest.mark.parametrize("present", [False, True])
def test_web_scout_switch_disables_it_on_a_gateway_turn(monkeypatch, tmp_path, caplog, switch, present):
    if present:
        monkeypatch.setenv("D3SKWEBSCOUT_DIR", str(_checkout(tmp_path)))
    monkeypatch.setenv("BRIDGE_WEB_SCOUT", switch)
    seen = _capture(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.web_scout"):
        resp = _post()
    _completed(resp, stream=False)
    assert seen["command"] == "claude"
    assert seen["web_scout"] is False
    assert _scout_logs(caplog) == []


@pytest.mark.parametrize("switch", [None, "1", "on", "true"])
@pytest.mark.parametrize("stream", [False, True])
def test_web_scout_missing_checkout_logs_one_line_and_the_turn_completes(
    monkeypatch, caplog, switch, stream
):
    if switch is not None:
        monkeypatch.setenv("BRIDGE_WEB_SCOUT", switch)
    seen = _capture(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.web_scout"):
        resp = _post(stream=stream)
    _completed(resp, stream=stream)
    scout = seen["web_scout"]
    assert isinstance(scout, WebScout) and scout.mode == "off"
    for is_live in (True, False):
        assert scout.cli_args("claude", is_live=is_live) == _NO_WEB_TOOLS
    assert scout.env("claude", {"PATH": "/bin"}) == {}
    assert "off for this turn" in scout.system_text("claude", "")
    records = _scout_logs(caplog)
    assert len(records) == 1
    assert records[0].message == _MISSING_CHECKOUT
    assert records[0].exc_info is None


def test_web_scout_checkout_present_is_used_on_a_gateway_turn(monkeypatch, tmp_path, caplog):
    checkout = _checkout(tmp_path)
    monkeypatch.setenv("D3SKWEBSCOUT_DIR", str(checkout))
    seen = _capture(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.web_scout"):
        resp = _post()
    _completed(resp, stream=False)
    scout = seen["web_scout"]
    assert isinstance(scout, WebScout) and scout.mode == "scout"
    assert scout.checkout() == checkout.resolve()
    args = scout.cli_args("claude", is_live=False)
    assert SEARCH_RULE in args[args.index("--allowedTools") + 1]
    assert _scout_logs(caplog) == []
