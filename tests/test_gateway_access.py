"""Client-token permission modes and cwd.

``owner_only_options`` is the allow/deny decision. The tests below call it with no
gateway process. The HTTP cases check that the chat route returns that decision.
"""
import stat
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_cli_bridge import gateway, gateway_auth  # noqa: E402
from agent_cli_bridge.gateway_auth import owner_only_options  # noqa: E402

CLIENT_TOKEN = "client-token-for-tests"
OWNER_TOKEN = "owner-token-for-tests"

FLAVORS = ("claude", "cursor", "antigravity", "gemini", "grok", "copilot", "opencode")
MODES = ("plan", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions")

# Everything not listed is owner-only for a client token.
_CLIENT_ALLOWED = {
    ("claude", "plan"),
    ("cursor", "plan"),
    ("cursor", "manual"),
    ("antigravity", "plan"),
    ("antigravity", "manual"),
    ("antigravity", "acceptEdits"),
    ("antigravity", "auto"),
    ("antigravity", "dontAsk"),
    ("gemini", "plan"),
    ("gemini", "manual"),
    ("grok", "plan"),
    ("grok", "manual"),
    ("grok", "acceptEdits"),
    ("grok", "dontAsk"),
    ("copilot", "plan"),
    ("opencode", "plan"),
    ("opencode", "manual"),
}


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})


@pytest.fixture
def fake_turn(monkeypatch):
    async def fake_run_agent(command, **kwargs):
        yield gateway.TextDelta(text="ok")

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)


def _client(token: str | None = CLIENT_TOKEN) -> TestClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(gateway.app, base_url="http://127.0.0.1:4747", headers=headers)


def _post(token: str, bridge: dict):
    return _client(token).post(
        "/v1/chat/completions",
        json={
            "model": "claude:sonnet",
            "messages": [{"role": "user", "content": "hi"}],
            "bridge": bridge,
        },
    )


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("mode", MODES)
def test_a_client_write_mode_is_owner_only_by_flavor(flavor, mode):
    reasons = owner_only_options({"permission_mode": mode}, flavor, workdir=None)
    denied = [reason for reason in reasons if reason.startswith("bridge.permission_mode=")]
    if (flavor, mode) in _CLIENT_ALLOWED:
        assert denied == []
    else:
        assert denied


def test_the_workdir_itself_is_an_allowed_client_cwd(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    assert owner_only_options({"cwd": str(work)}, "claude", workdir=str(work)) == []


def test_a_descendant_client_cwd_is_allowed(tmp_path):
    work = tmp_path / "work"
    nested = work / "a" / "b"
    nested.mkdir(parents=True)
    assert owner_only_options({"cwd": str(nested)}, "claude", workdir=str(work)) == []


def test_a_client_cwd_outside_the_workdir_is_owner_only(tmp_path):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    assert owner_only_options({"cwd": str(outside)}, "claude", workdir=str(work)) == ["bridge.cwd"]


def test_a_client_cwd_that_only_prefixes_the_workdir_is_owner_only(tmp_path):
    work = tmp_path / "work"
    sibling = tmp_path / "work-extra"
    work.mkdir()
    sibling.mkdir()
    reasons = owner_only_options({"cwd": str(sibling)}, "claude", workdir=str(work))
    assert reasons == ["bridge.cwd"]


def test_an_unset_workdir_makes_a_client_cwd_owner_only(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    assert owner_only_options({"cwd": str(work)}, "claude", workdir=None) == ["bridge.cwd"]
    assert owner_only_options({"cwd": str(work)}, "claude", workdir="   ") == ["bridge.cwd"]


def test_a_client_cwd_is_resolved_from_the_process_directory(tmp_path, monkeypatch):
    work = tmp_path / "work"
    nested = work / "nested"
    nested.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(tmp_path)
    assert owner_only_options({"cwd": "work"}, "claude", workdir="work") == []
    assert owner_only_options({"cwd": "work/nested"}, "claude", workdir="work") == []
    assert owner_only_options({"cwd": "outside"}, "claude", workdir="work") == ["bridge.cwd"]
    monkeypatch.chdir(work)
    climbed = owner_only_options({"cwd": "nested/../.."}, "claude", workdir=str(work))
    assert climbed == ["bridge.cwd"]


def test_a_symlink_client_cwd_that_escapes_the_workdir_is_owner_only(tmp_path):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    inner = work / "inner"
    work.mkdir()
    outside.mkdir()
    inner.mkdir()
    escape = work / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    stayed = work / "alias"
    stayed.symlink_to(inner, target_is_directory=True)
    link_root = tmp_path / "linked-work"
    link_root.symlink_to(work, target_is_directory=True)
    assert owner_only_options({"cwd": str(escape)}, "claude", workdir=str(work)) == ["bridge.cwd"]
    assert owner_only_options({"cwd": str(stayed)}, "claude", workdir=str(work)) == []
    assert owner_only_options({"cwd": str(work)}, "claude", workdir=str(link_root)) == []
    assert owner_only_options({"cwd": str(link_root / "inner")}, "claude", workdir=str(work)) == []


def test_a_client_cwd_outside_the_workdir_is_http_403(fake_turn, monkeypatch, tmp_path):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    nested = work / "nested"
    work.mkdir()
    outside.mkdir()
    nested.mkdir()
    monkeypatch.setenv("BRIDGE_WORKDIR", str(work))
    denied = _post(CLIENT_TOKEN, {"cwd": str(outside)})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "owner_token_required"
    assert "bridge.cwd" in denied.json()["error"]["message"]
    assert _post(CLIENT_TOKEN, {"cwd": str(work)}).status_code == 200
    assert _post(CLIENT_TOKEN, {"cwd": str(nested)}).status_code == 200


def test_a_missing_client_cwd_stays_http_400(fake_turn, monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("BRIDGE_WORKDIR", str(work))
    missing = _post(CLIENT_TOKEN, {"cwd": str(work / "missing")})
    assert missing.status_code == 400
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    still_missing = _post(CLIENT_TOKEN, {"cwd": str(tmp_path / "also-missing")})
    assert still_missing.status_code == 400


def test_a_relative_client_cwd_outside_the_workdir_is_http_403(fake_turn, monkeypatch, tmp_path):
    work = tmp_path / "work"
    (work / "nested").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "leak").symlink_to(outside, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRIDGE_WORKDIR", "work")
    assert _post(CLIENT_TOKEN, {"cwd": "work"}).status_code == 200
    assert _post(CLIENT_TOKEN, {"cwd": "work/nested"}).status_code == 200
    escaped = _post(CLIENT_TOKEN, {"cwd": "outside"})
    assert escaped.status_code == 403
    assert escaped.json()["error"]["code"] == "owner_token_required"
    leak = _post(CLIENT_TOKEN, {"cwd": "work/leak"})
    assert leak.status_code == 403
    assert leak.json()["error"]["code"] == "owner_token_required"


def test_an_unset_workdir_refuses_a_client_cwd_over_http(fake_turn, monkeypatch, tmp_path):
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    default = gateway_auth.default_workdir()
    default.mkdir(parents=True, exist_ok=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for path in (default, elsewhere):
        resp = _post(CLIENT_TOKEN, {"cwd": str(path)})
        assert resp.status_code == 403, path
        assert resp.json()["error"]["code"] == "owner_token_required"


def test_a_runtime_workdir_override_bounds_the_client_cwd(fake_turn, monkeypatch, tmp_path):
    env_work = tmp_path / "from-env"
    override = tmp_path / "from-override"
    env_work.mkdir()
    (override / "nested").mkdir(parents=True)
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    gateway._RUNTIME_CONFIG["workdir"] = str(override)
    assert _post(CLIENT_TOKEN, {"cwd": str(override)}).status_code == 200
    assert _post(CLIENT_TOKEN, {"cwd": str(override / "nested")}).status_code == 200
    monkeypatch.setenv("BRIDGE_WORKDIR", str(env_work))
    # The override still wins over the environment variable.
    denied = _post(CLIENT_TOKEN, {"cwd": str(env_work)})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "owner_token_required"
    assert _post(CLIENT_TOKEN, {"cwd": str(override)}).status_code == 200


@pytest.mark.parametrize(
    "model, mode",
    [
        ("claude:sonnet", "acceptEdits"),
        ("claude:sonnet", "auto"),
        ("claude:sonnet", "dontAsk"),
        ("claude:sonnet", "bypassPermissions"),
        ("grok", "auto"),
        ("grok", "acceptEdits"),
        ("copilot:auto", "manual"),
        ("opencode", "dontAsk"),
        ("agy", "acceptEdits"),
        ("agy", "bypassPermissions"),
        ("cursor-agent:auto", "dontAsk"),
        ("gemini:gemini-2.5-flash", "auto"),
    ],
)
def test_the_owner_token_may_send_every_write_mode(fake_turn, model, mode):
    resp = _client(OWNER_TOKEN).post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "bridge": {"permission_mode": mode},
        },
    )
    assert resp.status_code == 200, resp.text


def test_the_owner_token_may_set_a_cwd_outside_the_workdir(fake_turn, monkeypatch, tmp_path):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    monkeypatch.setenv("BRIDGE_WORKDIR", str(work))
    assert _post(OWNER_TOKEN, {"cwd": str(outside)}).status_code == 200
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    assert _post(OWNER_TOKEN, {"cwd": str(outside)}).status_code == 200


def test_the_default_workdir_is_beside_the_bridge_home_never_inside_it(monkeypatch, tmp_path):
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    monkeypatch.setenv(gateway_auth.HOME_ENV, str(tmp_path / "home"))
    home = gateway_auth.bridge_home_path()
    work = Path(gateway._workdir())
    assert work == gateway_auth.default_workdir()
    assert work == tmp_path / "home-work"
    assert work != home and home not in work.parents
    assert not (work / gateway_auth.TOKEN_FILE).exists()
    assert not (work.parent / gateway_auth.TOKEN_FILE).exists()
    if sys.platform != "win32":
        assert stat.S_IMODE(work.stat().st_mode) == 0o700


def test_a_configured_workdir_wins_over_the_default(monkeypatch, tmp_path):
    chosen = tmp_path / "chosen"
    monkeypatch.setenv("BRIDGE_WORKDIR", str(chosen))
    assert gateway._workdir() == str(chosen) and chosen.is_dir()
    other = tmp_path / "override"
    gateway._RUNTIME_CONFIG["workdir"] = str(other)
    assert gateway._workdir() == str(other) and other.is_dir()
