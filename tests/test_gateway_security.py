"""GET /api/security is owner-only. The static /security page stays public."""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_cli_bridge import gateway  # noqa: E402
from agent_cli_bridge.security_log import INJECTION_DETECTED, SecurityLog  # noqa: E402

CLIENT_TOKEN = "client-token-for-tests"
OWNER_TOKEN = "owner-token-for-tests"


@pytest.fixture(autouse=True)
def _gateway_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT_TOKEN)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER_TOKEN)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")


def _client(token: str | None = CLIENT_TOKEN) -> TestClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(gateway.app, base_url="http://127.0.0.1:4747", headers=headers)


def test_a_client_token_cannot_read_the_security_log():
    SecurityLog().record({"kind": INJECTION_DETECTED, "url": "https://risky.example/page"})
    resp = _client().get("/api/security")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "owner_token_required"
    assert "https://risky.example/page" not in resp.text


def test_the_owner_token_receives_the_security_log():
    SecurityLog().record({"kind": INJECTION_DETECTED, "url": "https://risky.example/page"})
    resp = _client(OWNER_TOKEN).get("/api/security")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"][0]["url"] == "https://risky.example/page"
    assert body["entries"][0]["kind"] == INJECTION_DETECTED


def test_the_security_page_stays_reachable_without_a_token():
    page = _client(token=None).get("/security")
    assert page.status_code == 200
    assert "Security log" in page.text
