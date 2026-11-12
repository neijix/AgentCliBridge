"""Gateway routing, transcript rendering, and endpoint smoke tests."""
import asyncio
import logging
import os
import stat
import sys

import pytest
from gateway_import import require_fastapi, test_fastapi_required_when_ci_is_set  # noqa: F401

require_fastapi(allow_module_level=True)
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import HTTPConnection  # noqa: E402

from agent_cli_bridge import gateway, gateway_sessions, upstream  # noqa: E402
from agent_cli_bridge.gateway import (  # noqa: E402
    parse_bridge_options,
    parse_cli_model,
    render_transcript,
)

CLIENT_TOKEN = "client-token-for-tests"
OWNER_TOKEN = "owner-token-for-tests"


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")


def _client(token: str | None = CLIENT_TOKEN) -> TestClient:
    """A caller on this machine (Host 127.0.0.1) holding ``token``."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(gateway.app, base_url="http://127.0.0.1:4747", headers=headers)


class TestModelRouting:
    def test_cli_route_with_submodel(self):
        spec, sub = parse_cli_model("claude:sonnet")
        assert spec.command == "claude"
        assert sub == "sonnet"

    def test_bare_command_uses_default_model(self):
        spec, sub = parse_cli_model("gemini")
        assert spec.command == "gemini"
        assert sub == "gemini-3.1-pro-preview"  # first curated entry

    def test_alias_routes(self):
        spec, sub = parse_cli_model("cursor-agent:auto")
        assert spec.command == "agent"
        assert sub == "auto"

    def test_copilot_routes(self):
        spec, sub = parse_cli_model("copilot:auto")
        assert spec.command == "copilot"
        assert sub == "auto"

    def test_unknown_model_goes_upstream(self):
        assert parse_cli_model("mlx-community/Qwen3-Coder-30B") is None
        assert parse_cli_model("gpt-4o") is None
        assert parse_cli_model("") is None


class TestTranscript:
    def test_single_turn_passthrough(self):
        system, prompt = render_transcript(
            [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "hello"},
            ]
        )
        assert system == "Be brief."
        assert prompt == "hello"

    def test_multi_turn_renders_history(self):
        system, prompt = render_transcript(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "second"},
            ]
        )
        assert "Conversation so far:" in prompt
        assert "User: first" in prompt
        assert "Assistant: answer" in prompt
        assert prompt.rstrip().endswith("second")

    def test_content_part_arrays(self):
        _, prompt = render_transcript(
            [{"role": "user", "content": [{"type": "text", "text": "hi there"}]}]
        )
        assert prompt == "hi there"

    def test_text_parts_are_separated_and_empty_ones_skipped(self):
        _, prompt = render_transcript(
            [{"role": "user", "content": [
                {"type": "text", "text": "page"}, {"type": "text", "text": ""}, {"type": "text", "text": "question"},
            ]}]
        )
        assert prompt == "page\n\nquestion"

    def test_a_developer_message_is_system_text(self):
        system, prompt = render_transcript(
            [{"role": "developer", "content": "Be brief."}, {"role": "user", "content": "hello"}]
        )
        assert (system, prompt) == ("Be brief.", "hello")

    def test_malformed_messages_have_no_prompt(self):
        for messages in (None, "hello", {"role": "user", "content": "hi"}, [1, None, "x"]):
            assert render_transcript(messages) == ("", "")


class TestBridgeOptions:
    def test_defaults_from_header_and_user_field(self):
        opts, err = parse_bridge_options({"user": "u1"}, {})
        assert err is None and opts["session"] == "u1"
        opts, err = parse_bridge_options({"user": "u1"}, {"x-bridge-session": "h1"})
        assert opts["session"] == "h1"  # header wins over user field

    def test_bridge_object_wins_and_validates(self, tmp_path):
        body = {
            "user": "u1",
            "bridge": {
                "session": "s1",
                "permission_mode": "acceptEdits",
                "cwd": str(tmp_path),
                "env": {"MY_URL": "http://127.0.0.1:1", "N": 3},
                "cli_args": ["--flag", 7],
            },
        }
        opts, err = parse_bridge_options(body, {})
        assert err is None
        assert opts["session"] == "s1"
        assert opts["permission_mode"] == "acceptEdits"
        assert opts["cwd"] == str(tmp_path)
        assert opts["env"] == {"MY_URL": "http://127.0.0.1:1", "N": "3"}
        assert opts["cli_args"] == ["--flag", "7"]

    def test_invalid_inputs_are_rejected(self, tmp_path):
        _, err = parse_bridge_options({"bridge": {"permission_mode": "yolo!"}}, {})
        assert err and "permission mode" in err
        _, err = parse_bridge_options({"bridge": {"cwd": str(tmp_path / "nope")}}, {})
        assert err and "does not exist" in err
        _, err = parse_bridge_options({"bridge": {"env": ["not-a-dict"]}}, {})
        assert err and "env" in err
        _, err = parse_bridge_options({"bridge": "not-an-object"}, {})
        assert err and "object" in err

    def test_bad_bridge_returns_400_over_http(self):
        client = _client()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude:sonnet",
                "messages": [{"role": "user", "content": "hi"}],
                "bridge": {"permission_mode": "nonsense"},
            },
        )
        assert resp.status_code == 400


class TestDurableSessions:
    def test_sessions_survive_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gateway_sessions, "_sessions_file", lambda: tmp_path / "sessions.json")
        gateway_sessions._sessions.clear()
        gateway_sessions._session_put("claude", CLIENT_TOKEN, "conv-1", "resume-abc")
        assert (tmp_path / "sessions.json").exists()
        # Simulate a restart: empty map, then reload from disk.
        gateway_sessions._sessions.clear()
        assert gateway_sessions._session_get("claude", CLIENT_TOKEN, "conv-1") is None
        gateway_sessions._load_sessions()
        assert gateway_sessions._session_get("claude", CLIENT_TOKEN, "conv-1") == "resume-abc"
        gateway_sessions._sessions.clear()

    def test_sessions_file_mode_bits_are_private(self, tmp_path, monkeypatch):
        path = tmp_path / "sessions.json"
        monkeypatch.setattr(gateway_sessions, "_sessions_file", lambda: path)
        gateway_sessions._sessions.clear()
        gateway_sessions._sessions_loaded = False
        gateway_sessions._session_put("claude", CLIENT_TOKEN, "conv-1", "resume-abc")
        if sys.platform != "win32":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        gateway_sessions._sessions.clear()
        gateway_sessions._sessions_loaded = False

    def test_a_non_object_sessions_file_is_logged_and_ignored(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "sessions.json"
        monkeypatch.setattr(gateway_sessions, "_sessions_file", lambda: path)
        path.write_text("[1, 2]", encoding="utf-8")
        gateway_sessions._sessions.clear()
        gateway_sessions._sessions_loaded = False
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway_sessions"):
            assert gateway_sessions._session_get("claude", CLIENT_TOKEN, "conv-1") is None
        assert not gateway_sessions._sessions
        assert "not a JSON object" in caplog.text
        caplog.clear()
        path.write_text("{", encoding="utf-8")
        gateway_sessions._sessions.clear()
        gateway_sessions._sessions_loaded = False
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway_sessions"):
            assert gateway_sessions._session_get("claude", CLIENT_TOKEN, "other") is None
        assert not gateway_sessions._sessions
        assert "not a JSON object" in caplog.text
        gateway_sessions._sessions_loaded = False


class TestEndpoints:
    def test_models_lists_installed_clis_and_survives_upstream_down(self, monkeypatch):
        # Pretend only claude is installed; point upstream at a dead port.
        monkeypatch.setattr(
            gateway, "resolve_binary",
            lambda cmd: "/bin/claude" if cmd == "claude" else None,
        )
        monkeypatch.setenv("BRIDGE_UPSTREAM_OPENAI", "http://127.0.0.1:1/v1")
        client = _client()
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["data"]]
        assert "claude:sonnet" in ids
        assert not any(i.startswith("gemini:") for i in ids)

    def test_health(self, monkeypatch):
        monkeypatch.setattr(gateway, "resolve_binary", lambda cmd: None)
        client = _client()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert {a["command"] for a in body["agents"]} >= {"claude", "gemini", "copilot"}

    def test_chat_requires_user_message(self):
        client = _client()
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "claude:sonnet", "messages": [{"role": "system", "content": "x"}]},
        )
        assert resp.status_code == 400

    def test_upstream_unreachable_is_clean_502(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_UPSTREAM_OPENAI", "http://127.0.0.1:1/v1")
        client = _client()
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mlx-something", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "upstream_unreachable"


class TestUpstreamAgent:
    """The passthrough upstream is surfaced as a synthetic 'mlx' agent."""

    def test_status_lists_upstream_when_reachable(self, monkeypatch):
        async def fake_probe():
            return {
                "url": "http://127.0.0.1:8899/v1",
                "reachable": True,
                "models": 2,
                "model_ids": ["mlx-community/A", "mlx-community/B"],
            }

        monkeypatch.setattr(gateway, "_probe_upstream", fake_probe)
        client = _client()
        resp = client.get("/api/status")
        assert resp.status_code == 200
        by_cmd = {a["command"]: a for a in resp.json()["agents"]}
        assert "mlx" in by_cmd
        mlx = by_cmd["mlx"]
        assert mlx["installed"] is True
        assert mlx["models"] == ["mlx-community/A", "mlx-community/B"]
        assert mlx["install_hint"] == ""

    def test_status_marks_upstream_not_installed_when_down(self, monkeypatch):
        async def fake_probe():
            return {
                "url": "http://127.0.0.1:1/v1",
                "reachable": False,
                "models": 0,
                "model_ids": [],
            }

        monkeypatch.setattr(gateway, "_probe_upstream", fake_probe)
        client = _client()
        resp = client.get("/api/status")
        mlx = next(a for a in resp.json()["agents"] if a["command"] == "mlx")
        assert mlx["installed"] is False
        assert mlx["models"] == []
        assert "http://127.0.0.1:1/v1" in mlx["install_hint"]

    def test_models_tags_upstream_ids_with_mlx_prefix(self, monkeypatch):
        monkeypatch.setattr(gateway, "resolve_binary", lambda cmd: None)

        class _Resp:
            status_code = 200

            def json(self):
                return {"data": [{"id": "mlx-community/X"}]}

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, _url):
                return _Resp()

        monkeypatch.setattr(upstream.httpx, "AsyncClient", _Client)
        client = _client()
        resp = client.get("/v1/models")
        ids = [m["id"] for m in resp.json()["data"]]
        assert "mlx:mlx-community/X" in ids

    def test_proxy_strips_mlx_prefix_before_forwarding(self, monkeypatch):
        captured: dict = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"id": "ok"}

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json):
                captured["url"] = url
                captured["body"] = json
                return _Resp()

        monkeypatch.setattr(upstream.httpx, "AsyncClient", _Client)
        client = _client()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mlx:mlx-community/Qwen",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        # Prefix stripped so the upstream sees its own model id verbatim.
        assert captured["body"]["model"] == "mlx-community/Qwen"


class TestAccess:
    """Host and Origin on this machine, a bearer token, and owner-only options."""

    def test_api_needs_a_bearer_token(self):
        resp = _client(token=None).get("/api/status")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"
        assert _client(token="wrong").get("/health").status_code == 401

    def test_static_pages_need_no_token(self):
        assert _client(token=None).get("/").status_code == 200
        assert _client(token=None).get("/security").status_code == 200

    def test_foreign_host_is_refused_even_with_a_token(self, monkeypatch):
        monkeypatch.setattr(gateway, "resolve_binary", lambda cmd: None)
        for host in ("evil.example", "localhost.evil.example", "127.0.0.1.nip.io:4747"):
            resp = _client().get("/health", headers={"Host": host})
            assert resp.status_code == 403, host
            assert resp.json()["error"]["code"] == "forbidden_host"
        for host in ("localhost:4747", "[::1]:4747", "127.0.0.1"):
            assert _client().get("/health", headers={"Host": host}).status_code == 200, host

    def test_foreign_origin_is_refused_even_with_a_token(self, monkeypatch):
        monkeypatch.setattr(gateway, "resolve_binary", lambda cmd: None)
        for origin in ("https://evil.example", "null", "http://localhost.evil.example"):
            resp = _client().get("/health", headers={"Origin": origin})
            assert resp.status_code == 403, origin
            assert resp.json()["error"]["code"] == "forbidden_origin"
        assert _client(token=None).get("/", headers={"Origin": "https://evil.example"}).status_code == 403
        for origin in ("http://localhost:5173", "http://127.0.0.1:3000", "http://[::1]:3000"):
            resp = _client().get("/health", headers={"Origin": origin})
            assert resp.status_code == 403, origin  # a local page on another port
            assert resp.json()["error"]["code"] == "forbidden_origin"
        assert _client().get("/health", headers={"Origin": "http://127.0.0.1:4747"}).status_code == 200
        resp = _client().get("/health", headers={"Origin": "http://localhost:4747"})
        assert resp.status_code == 403  # another loopback name: maybe another server on that port

    @pytest.mark.parametrize(
        "bridge, refused",
        [
            ({"permission_mode": "bypassPermissions"}, "bypassPermissions"),
            ({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:1"}}, "bridge.env"),
            ({"cli_args": ["--dangerously-skip-permissions"]}, "bridge.cli_args"),
        ],
    )
    def test_client_token_cannot_lift_a_turns_limits(self, monkeypatch, bridge, refused):
        def must_not_run(*args, **kwargs):
            raise AssertionError("the CLI must not start")

        monkeypatch.setattr(gateway, "run_agent", must_not_run)
        resp = _client().post(
            "/v1/chat/completions",
            json={"model": "claude:sonnet", "messages": [{"role": "user", "content": "hi"}],
                  "bridge": bridge},
        )
        assert resp.status_code == 403
        error = resp.json()["error"]
        assert error["code"] == "owner_token_required"
        assert refused in error["message"]

    @pytest.mark.parametrize(
        "model, mode, is_owner_only",
        [
            ("gemini:gemini-2.5-flash", "acceptEdits", True),  # --approval-mode yolo, as bypass
            ("gemini:gemini-2.5-flash", "manual", False),
            ("copilot:auto", "auto", True),                     # --allow-all-tools, as bypass
            ("copilot:auto", "manual", True),                   # manual is --allow-all-tools too
            ("copilot:auto", "plan", False),
            ("cursor-agent:auto", "acceptEdits", True),         # --force, as bypass
            ("cursor-agent:auto", "manual", False),
            ("gemini:gemini-2.5-flash", "plan", False),
            ("claude:sonnet", "auto", True),                    # write mode, client token refused
            ("claude:sonnet", "acceptEdits", True),
            ("claude:sonnet", "dontAsk", True),
            ("claude:sonnet", "manual", True),                  # its default tool list holds Bash
            ("claude:sonnet", "plan", False),
            ("grok", "acceptEdits", False),                    # argv denies Bash
            ("grok", "dontAsk", False),
            ("grok", "auto", True),
            ("agy", "acceptEdits", False),                     # file edits, not a pre-approved shell
            ("agy", "auto", False),
            ("agy", "dontAsk", False),
            ("agy", "manual", False),
            ("opencode", "acceptEdits", True),
            ("opencode", "auto", True),
            ("opencode", "dontAsk", True),
            ("opencode", "manual", False),
            ("opencode", "plan", False),
        ],
    )
    def test_a_mode_that_approves_everything_for_that_cli_is_owner_only(
        self, monkeypatch, model, mode, is_owner_only
    ):
        async def fake_run_agent(command, **kwargs):
            yield gateway.TextDelta(text="ok")

        monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
        resp = _client().post(
            "/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                  "bridge": {"permission_mode": mode}},
        )
        assert resp.status_code == (403 if is_owner_only else 200), resp.text
        if is_owner_only:
            assert resp.json()["error"]["code"] == "owner_token_required"

    def test_a_streamed_turn_goes_through_the_guard(self, monkeypatch):
        async def fake_run_agent(command, **kwargs):
            yield gateway.TextDelta(text="hel")
            yield gateway.TextDelta(text="lo")

        monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
        resp = _client().post(
            "/v1/chat/completions",
            json={"model": "claude:sonnet", "stream": True,
                  "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert '"content": "hel"' in resp.text and resp.text.rstrip().endswith("data: [DONE]")

    def test_owner_token_may_send_them(self, monkeypatch, tmp_path):
        seen: dict = {}

        async def fake_run_agent(command, **kwargs):
            seen.update(kwargs)
            yield gateway.TextDelta(text="ok")

        monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
        monkeypatch.setenv("BRIDGE_WORKDIR", str(tmp_path))
        resp = _client(OWNER_TOKEN).post(
            "/v1/chat/completions",
            json={
                "model": "claude:sonnet",
                "messages": [{"role": "user", "content": "hi"}],
                "bridge": {"permission_mode": "bypassPermissions", "env": {"A": "1"},
                           "cli_args": ["--x"]},
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["choices"][0]["message"]["content"] == "ok"
        assert seen["permission_mode"] == "bypassPermissions"
        assert seen["extra_env"] == {"A": "1"}
        assert seen["cli_args"] == ["--x"]

    def test_client_token_keeps_the_other_options(self, monkeypatch, tmp_path):
        async def fake_run_agent(command, **kwargs):
            yield gateway.TextDelta(text="ok")

        monkeypatch.setattr(gateway, "run_agent", fake_run_agent)
        monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})
        monkeypatch.setenv("BRIDGE_WORKDIR", str(tmp_path))
        resp = _client().post(
            "/v1/chat/completions",
            json={"model": "claude:sonnet", "messages": [{"role": "user", "content": "hi"}],
                  "bridge": {"permission_mode": "plan", "cwd": str(tmp_path),
                             "env": {}, "cli_args": []}},
        )
        assert resp.status_code == 200, resp.text

    def test_config_and_log_clearing_are_owner_only(self, monkeypatch):
        monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})
        resp = _client().post("/api/config", json={"permission_mode": "bypassPermissions"})
        assert resp.status_code == 403
        assert gateway._permission_mode() != "bypassPermissions"
        assert _client().delete("/api/security").status_code == 403
        assert _client().get("/api/config").status_code == 200

        resp = _client(OWNER_TOKEN).post("/api/config", json={"permission_mode": "acceptEdits"})
        assert resp.status_code == 200
        assert resp.json()["permission_mode"] == "acceptEdits"
        assert _client(OWNER_TOKEN).delete("/api/security").status_code == 200

    def test_public_page_bypass_is_only_get_and_head(self):
        anonymous = _client(token=None)
        for path in ("/", "/security"):
            assert anonymous.get(path).status_code == 200
            # Auth is skipped; the route itself has no HEAD handler, so this is 405, not 401.
            assert anonymous.head(path).status_code != 401
            for method in ("POST", "PUT", "DELETE"):
                assert anonymous.request(method, path).status_code == 401, (method, path)
        for path in ("/health", "/api/status", "/api/config", "/api/security", "/v1/models"):
            assert anonymous.get(path).status_code == 401, path
            assert anonymous.head(path).status_code == 401, path

    def test_bad_mode_on_post_config_is_400(self, monkeypatch):
        monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})
        resp = _client(OWNER_TOKEN).post("/api/config", json={"permission_mode": "yolo"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "bad_request"
        assert "yolo" not in gateway._RUNTIME_CONFIG.values()

    def test_token_read_error_returns_token_unavailable(self, monkeypatch):
        monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
        monkeypatch.delenv("BRIDGE_OWNER_TOKEN", raising=False)
        real_open = os.open

        def open_token_fails(path, flags, *args, **kwargs):
            text = os.fsdecode(path)
            names = (gateway.gateway_auth.OWNER_TOKEN_FILE, gateway.gateway_auth.TOKEN_FILE)
            if text.endswith(names):
                raise OSError("unexpected token read failure")
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", open_token_fails)
        resp = _client(token="presented-token").get("/health")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "token_unavailable"

    def test_websocket_that_fails_the_caller_check_is_refused(self, monkeypatch):
        """Close 1008, and do not call the app, when the bearer check fails.

        Starlette's Request asserts an http scope, so the guard's ``Request(scope)``
        never reaches the close on a real websocket. This connection exposes the
        attributes the guard reads and lets that close run.
        """

        class _AnyScopeRequest(HTTPConnection):
            def __init__(self, scope, receive=None, send=None):
                super().__init__(scope)

            @property
            def method(self) -> str:
                return str(self.scope.get("method", "GET"))

        monkeypatch.setattr(gateway, "Request", _AnyScopeRequest)
        sent: list[dict] = []
        reached: list[bool] = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        async def app(scope, receive, send):
            reached.append(True)

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "method": "GET",
            "path": "/v1/chat",
            "raw_path": b"/v1/chat",
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:4747")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 4747),
            "subprotocols": [],
            "state": {},
            "root_path": "",
        }
        asyncio.run(gateway.LocalCallerGuard(app)(scope, receive, send))
        assert reached == []
        assert sent == [{"type": "websocket.close", "code": 1008}]

    def test_bind_host_is_127_0_0_1(self, monkeypatch):
        captured: dict = {}

        def fake_run(app, *args, **kwargs):
            captured["app"] = app
            captured["args"] = args
            captured["host"] = kwargs.get("host")

        import uvicorn

        monkeypatch.setattr(uvicorn, "run", fake_run)
        gateway.main()
        assert captured["app"] is gateway.app
        assert captured["args"] == ()
        assert captured["host"] == "127.0.0.1"


@pytest.mark.parametrize("path", ["/", "/security"])
def test_the_pages_cannot_be_framed(path):
    resp = _client(token=None).get(path)
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert resp.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "model",
    [
        "gemini:--yolo", "claude:-p", "claude:--dangerously-skip-permissions", "agent:--force",
        "claude: -p", "claude:sonnet;id", "claude:$(id)", "claude:a\nb",
        "claude:" + "m" * 129, "claude:.hidden", "claude:\u00e9",
    ],
)
@pytest.mark.parametrize("token", [CLIENT_TOKEN, OWNER_TOKEN])
def test_a_model_id_that_could_be_a_cli_flag_is_400(monkeypatch, model, token):
    def must_not_run(*args, **kwargs):
        raise AssertionError("the CLI must not start")

    monkeypatch.setattr(gateway, "run_agent", must_not_run)
    for route in ("/v1/chat/completions", "/browser/v1/chat/completions"):
        resp = _client(token).post(
            route, json={"model": model, "messages": [{"role": "user", "content": "hi"}]}
        )
        assert resp.status_code == 400, (route, resp.text)
        if model.startswith("claude:"):
            assert resp.json()["error"]["code"] == "bad_request"


def test_every_listed_model_id_passes_the_id_check(monkeypatch):
    from agent_cli_bridge.specs import CLI_AGENT_SPECS

    ids = [m for spec in CLI_AGENT_SPECS for m in spec.models]
    ids += ["Claude Code", "claude-opus-5-5[1m]", "openrouter/anthropic/claude-3.5-sonnet:free", "gpt-5.1-codex@high"]
    assert ids
    for model_id in ids:
        assert gateway._bad_model_id(model_id) is None, model_id
    assert gateway._bad_model_id(None) is None
