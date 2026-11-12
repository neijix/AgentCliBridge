"""gateway_auth: local Host / Origin rules and the two bearer tokens."""
import hmac
import os
import secrets
import stat
import sys

import pytest

from agent_cli_bridge import gateway_auth
from agent_cli_bridge.gateway_auth import (
    bearer_token,
    caller_role,
    is_local_host,
    is_local_origin,
    load_token,
)


@pytest.fixture(autouse=True)
def _no_token_env(monkeypatch):
    monkeypatch.delenv(gateway_auth.TOKEN_ENV, raising=False)
    monkeypatch.delenv(gateway_auth.OWNER_TOKEN_ENV, raising=False)


@pytest.mark.parametrize("origin, host", [
    (None, "127.0.0.1:4747"), ("", "127.0.0.1:4747"), ("http://127.0.0.1:4747", "127.0.0.1:4747"),
    ("http://localhost:4747", "localhost:4747"), ("http://[::1]:4747", "[::1]:4747"),
    ("http://LOCALHOST:4747", "localhost:4747"),
])
def test_the_gateways_own_origins_and_no_origin_pass(origin, host):
    assert is_local_origin(origin, host)


def test_another_loopback_name_on_the_same_port_is_another_server():
    assert not is_local_origin("http://[::1]:4747", "127.0.0.1:4747")
    assert not is_local_origin("http://localhost:4747", "127.0.0.1:4747")


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://localhost.evil.example",
                                    "http://127.0.0.1.nip.io", "file://", "chrome-extension://abc",
                                    "http://[::1", "http://localhost:5173", "http://127.0.0.1:3000",
                                    "http://localhost", "https://127.0.0.1:4747"])
def test_foreign_origins(origin):
    assert not is_local_origin(origin, "127.0.0.1:4747")


def test_an_origin_must_use_the_hosts_port():
    assert is_local_origin("http://localhost", "localhost")
    assert is_local_origin("http://localhost:8080", "localhost:8080")
    assert not is_local_origin("http://localhost:4747", "localhost:8080")
    assert not is_local_origin("http://localhost:4747", None)


@pytest.mark.parametrize("host", ["127.0.0.1:4747", "localhost", "[::1]:4747", "LocalHost:1"])
def test_local_hosts(host):
    assert is_local_host(host)


@pytest.mark.parametrize("host", [None, "", "evil.example", "127.0.0.1.nip.io", "localhost:abc",
                                  "localhost@evil.example", "evil@localhost", "localhost/x",
                                  "localhost?x", "localhost#x", "local host", "[::1"])
def test_foreign_hosts(host):
    assert not is_local_host(host)


def test_bearer_token_parsing():
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer  abc ") == "abc"
    assert bearer_token("Basic abc") == ""
    assert bearer_token(None) == ""


def test_token_file_is_created_once_and_private(tmp_path):
    first = load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert len(first) >= 32
    assert load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path) == first
    if sys.platform != "win32":
        assert stat.S_IMODE((tmp_path / "tok").stat().st_mode) == 0o600


def test_an_empty_token_file_is_replaced(tmp_path):
    (tmp_path / "tok").write_text("")
    token = load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert token and (tmp_path / "tok").read_text().strip() == token


def test_env_token_wins_over_the_file(tmp_path, monkeypatch):
    path = tmp_path / "tok"
    path.write_text("from-file\n")
    if sys.platform != "win32":
        path.chmod(0o600)  # a group-readable token is rejected; this case is the env var winning
    assert load_token("ACB_TEST_TOKEN", "tok", tmp_path) == "from-file"
    monkeypatch.setenv("ACB_TEST_TOKEN", "from-env")
    assert load_token("ACB_TEST_TOKEN", "tok", tmp_path) == "from-env"


def test_bridge_home_mode_bits_are_private(tmp_path, monkeypatch):
    home = tmp_path / "bridge"
    home.mkdir()
    if sys.platform != "win32":
        home.chmod(0o755)
    monkeypatch.setenv(gateway_auth.HOME_ENV, str(home))
    assert gateway_auth.bridge_home() == home
    if sys.platform != "win32":
        assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_an_empty_token_file_refill_resets_mode_bits(tmp_path):
    path = tmp_path / "tok"
    path.write_text("")
    if sys.platform != "win32":
        path.chmod(0o644)
    token = load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert path.read_text().strip() == token
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_token_mode_bits_reject_group_or_other(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX mode bits")
    path = tmp_path / "tok"
    path.write_text("loose-token-value\n")
    path.chmod(0o640)
    with pytest.raises(OSError):
        load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert path.read_text() == "loose-token-value\n"


def test_token_mode_bits_reject_another_owner(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX owner check")
    path = tmp_path / "tok"
    path.write_text("their-token\n")
    path.chmod(0o600)
    uid = path.stat().st_uid
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    with pytest.raises(OSError):
        load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert path.read_text() == "their-token\n"


def test_a_token_symlink_is_not_followed(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX symlink")
    secret = tmp_path / "secret"
    secret.write_text("super-secret-token\n")
    (tmp_path / "tok").symlink_to(secret)
    with pytest.raises(OSError):
        load_token("ACB_NO_SUCH_TOKEN_ENV", "tok", tmp_path)
    assert secret.read_text() == "super-secret-token\n"


def test_caller_role(tmp_path):
    client = gateway_auth.client_token(tmp_path)
    owner = gateway_auth.owner_token(tmp_path)
    assert client != owner
    assert caller_role(f"Bearer {owner}", tmp_path) == "owner"
    assert caller_role(f"Bearer {client}", tmp_path) == "client"
    assert caller_role("Bearer nope", tmp_path) is None
    assert caller_role(None, tmp_path) is None


def test_constant_time_token_compare(tmp_path, monkeypatch):
    """The bearer match is whatever compare_digest returns; ``==`` must not decide it."""
    client = gateway_auth.client_token(tmp_path)
    calls = {"n": 0}

    def refuse(_presented: bytes, _expected: bytes) -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(hmac, "compare_digest", refuse)
    monkeypatch.setattr(secrets, "compare_digest", refuse)
    assert caller_role(f"Bearer {client}", tmp_path) is None
    assert calls["n"] >= 1

    def accept(_presented: bytes, _expected: bytes) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(hmac, "compare_digest", accept)
    monkeypatch.setattr(secrets, "compare_digest", accept)
    assert caller_role("Bearer not-a-token", tmp_path) == "owner"
