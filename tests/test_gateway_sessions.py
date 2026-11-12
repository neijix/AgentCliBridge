"""Resume only for an explicit session, keyed by a hash of the bearer token."""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_cli_bridge import gateway_sessions

CLIENT = "client-token-for-tests"
OWNER = "owner-token-for-tests"
_LOADER_NAMES = frozenset({"_load_sessions", "_ensure_sessions_loaded"})


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _walk_outside_functions(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        yield from _walk_outside_functions(child)


def _module_loads_sessions_at_import(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in _walk_outside_functions(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in _LOADER_NAMES:
            return True
    return False


@pytest.fixture(autouse=True)
def sessions_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the store at a temp file and put the in-memory map back afterwards."""
    path = tmp_path / "sessions.json"
    saved = dict(gateway_sessions._sessions)
    loaded = gateway_sessions._sessions_loaded
    monkeypatch.setattr(gateway_sessions, "_sessions_file", lambda: path)
    gateway_sessions._sessions.clear()
    monkeypatch.setattr(gateway_sessions, "_sessions_loaded", False)
    yield path
    gateway_sessions._sessions.clear()
    gateway_sessions._sessions.update(saved)
    gateway_sessions._sessions_loaded = loaded


def test_explicit_session_id_order() -> None:
    body = {"user": "from-user", "bridge": {"session": "from-bridge"}}
    headers = {"X-Bridge-Session": "from-header"}
    assert gateway_sessions.explicit_session_id(body, headers) == "from-bridge"
    assert gateway_sessions.explicit_session_id({"user": "from-user"}, headers) == "from-header"
    assert gateway_sessions.explicit_session_id({"user": "from-user"}, {}) == "from-user"
    # An empty bridge.session falls through; the literal user "default" does not resume.
    assert gateway_sessions.explicit_session_id(
        {"user": "from-user", "bridge": {"session": ""}}, headers
    ) == "from-header"
    assert gateway_sessions.explicit_session_id({"user": "default"}, {}) is None
    assert gateway_sessions.explicit_session_id({"user": ""}, {}) is None
    assert gateway_sessions.explicit_session_id({}, {}) is None
    assert gateway_sessions.explicit_session_id({"user": "dev.user-1_a"}, {}) == "dev.user-1_a"
    # "default" is still an explicit id when the caller set it on purpose.
    assert gateway_sessions.explicit_session_id({"user": "default"}, headers) == "from-header"
    assert gateway_sessions.explicit_session_id(
        {"user": "default", "bridge": {"session": "default"}}, {}
    ) == "default"
    lower = {"x-bridge-session": "folded"}
    assert gateway_sessions.explicit_session_id({"user": "default"}, lower) == "folded"


ODD_SESSION_IDS = ["a|b", "has space", "x" * 129, "naïve", "../escape", "a/b", "line\nbreak", "a:b"]


@pytest.mark.parametrize("session_id", ["a", "conv-1", "A.b_c-9", "x" * 128])
def test_a_plain_session_id_is_valid(session_id: str) -> None:
    assert gateway_sessions.is_valid_session_id(session_id)


@pytest.mark.parametrize("session_id", ODD_SESSION_IDS + [""])
def test_an_odd_session_id_is_not_valid(session_id: str) -> None:
    assert not gateway_sessions.is_valid_session_id(session_id)


@pytest.mark.parametrize("session_id", ODD_SESSION_IDS)
def test_an_odd_bridge_session_or_header_is_refused_and_an_odd_user_is_no_session(
    session_id: str,
) -> None:
    pytest.importorskip("fastapi")
    from agent_cli_bridge.gateway import parse_bridge_options

    for body, headers in (
        ({"bridge": {"session": session_id}}, {}),
        ({}, {"x-bridge-session": session_id}),
    ):
        opts, err = parse_bridge_options(body, headers)
        assert err is not None and "128" in err
    opts, err = parse_bridge_options({"user": session_id}, {})
    assert err is None and opts["session"] is None


def test_parse_bridge_options_keeps_header_over_user_and_drops_default() -> None:
    pytest.importorskip("fastapi")
    from agent_cli_bridge.gateway import parse_bridge_options

    opts, err = parse_bridge_options({"user": "u1"}, {})
    assert err is None and opts["session"] == "u1"
    opts, err = parse_bridge_options({"user": "u1"}, {"x-bridge-session": "h1"})
    assert opts["session"] == "h1"
    opts, err = parse_bridge_options({"user": "default"}, {})
    assert opts["session"] is None
    opts, err = parse_bridge_options(
        {"user": "default", "bridge": {"session": "s1"}}, {"x-bridge-session": "h1"}
    )
    assert opts["session"] == "s1"


def test_on_disk_key_is_command_digest_session_and_omits_the_token(sessions_file: Path) -> None:
    gateway_sessions._session_put("claude", "token-a", "conv-1", "resume-abc")
    text = sessions_file.read_text(encoding="utf-8")
    assert "token-a" not in text
    stored = json.loads(text)
    assert stored == {f"claude|{_digest('token-a')}|conv-1": "resume-abc"}
    gateway_sessions._sessions.clear()
    gateway_sessions._sessions_loaded = False
    assert gateway_sessions._session_get("claude", "token-a", "conv-1") == "resume-abc"
    assert gateway_sessions._session_get("claude", "token-b", "conv-1") is None


def test_two_tokens_do_not_share_a_session(sessions_file: Path) -> None:
    gateway_sessions._session_put("claude", "token-a", "conv", "resume-a")
    gateway_sessions._session_put("claude", "token-b", "conv", "resume-b")
    assert gateway_sessions._session_get("claude", "token-a", "conv") == "resume-a"
    assert gateway_sessions._session_get("claude", "token-b", "conv") == "resume-b"
    text = sessions_file.read_text(encoding="utf-8")
    assert "token-a" not in text and "token-b" not in text
    assert set(json.loads(text)) == {
        f"claude|{_digest('token-a')}|conv",
        f"claude|{_digest('token-b')}|conv",
    }


def test_malformed_session_entries_are_skipped(sessions_file: Path) -> None:
    digest = _digest("token-a")
    sessions_file.write_text(
        json.dumps(
            {
                f"claude|{digest}|conv-1": "keep",
                "claude|conv-1": "old-two-field",
                f"claude|{digest}|conv-1|extra": "four-fields",
                f"claude||{digest}": "empty-field",
                f"|{digest}|conv-1": "empty-command",
                f"claude|{digest}|": "empty-session",
                "nosep": "one-field",
                f"claude|{digest}|numeric": 3,
            }
        ),
        encoding="utf-8",
    )
    gateway_sessions._sessions_loaded = False
    assert gateway_sessions._session_get("claude", "token-a", "conv-1") == "keep"
    assert len(gateway_sessions._sessions) == 1
    assert gateway_sessions._session_get("claude", "token-a", "numeric") is None


def test_a_non_object_sessions_file_is_logged_and_ignored(
    sessions_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for text in ("[1, 2]", "{", "42", '"nope"'):
        sessions_file.write_text(text, encoding="utf-8")
        gateway_sessions._sessions.clear()
        gateway_sessions._sessions_loaded = False
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway_sessions"):
            assert gateway_sessions._session_get("claude", "token-a", "conv-1") is None
        assert not gateway_sessions._sessions
        assert "not a JSON object" in caplog.text


def test_sessions_file_mode_bits_are_private(sessions_file: Path) -> None:
    gateway_sessions._session_put("claude", "token-a", "conv-1", "resume-abc")
    if sys.platform != "win32":
        assert stat.S_IMODE(sessions_file.stat().st_mode) == 0o600


def test_a_failed_save_is_logged_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(gateway_sessions.gateway_auth, "write_private", boom)
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway_sessions"):
        gateway_sessions._session_put("claude", "token-a", "conv-1", "resume-abc")
    assert "could not save the sessions file" in caplog.text
    assert gateway_sessions._session_get("claude", "token-a", "conv-1") == "resume-abc"


def test_sessions_json_is_not_loaded_at_import(tmp_path: Path) -> None:
    home = tmp_path / "fresh-home"
    home.mkdir()
    digest = "ab" * 32
    (home / "sessions.json").write_text(
        json.dumps({f"claude|{digest}|sentinel": "resume-sentinel"}),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["AGENT_CLI_BRIDGE_HOME"] = str(home)
    env["BRIDGE_WORKDIR"] = str(tmp_path / "work")
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "import os\n"
        "from pathlib import Path\n"
        "from agent_cli_bridge.gateway_auth import bridge_home_path\n"
        "import agent_cli_bridge.gateway_sessions as sessions\n"
        "assert bridge_home_path() == Path(os.environ['AGENT_CLI_BRIDGE_HOME'])\n"
        "assert sessions._sessions_loaded is False\n"
        "assert not sessions._sessions\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert not _module_loads_sessions_at_import(root / "agent_cli_bridge" / "gateway_sessions.py")
    assert not _module_loads_sessions_at_import(root / "agent_cli_bridge" / "gateway.py")


def _chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agent_cli_bridge import gateway

    monkeypatch.setenv("BRIDGE_TOKEN", CLIENT)
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", OWNER)
    monkeypatch.setattr(gateway.gateway_auth, "bridge_home", lambda: tmp_path / "tokens")
    seen: list[str | None] = []

    async def fake_run_agent(command: str, **kwargs: object):
        resume_id = kwargs.get("resume_id")
        seen.append(resume_id if isinstance(resume_id, str) or resume_id is None else str(resume_id))
        yield gateway.SessionUpdate(session_id=f"resume-{len(seen)}")
        yield gateway.TextDelta(text="ok")

    monkeypatch.setattr(gateway, "run_agent", fake_run_agent)

    def post(
        body: dict[str, object],
        token: str = CLIENT,
        headers: dict[str, str] | None = None,
    ):
        extra = {"Authorization": f"Bearer {token}"}
        if headers:
            extra.update(headers)
        client = TestClient(gateway.app, base_url="http://127.0.0.1:4747", headers=extra)
        return client.post("/v1/chat/completions", json=body)

    return post, seen


def _turn(user: str | None = None, session: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "model": "claude:sonnet",
        "messages": [{"role": "user", "content": "hi"}],
    }
    if user is not None:
        body["user"] = user
    if session is not None:
        body["bridge"] = {"session": session}
    return body


def test_user_default_requests_do_not_resume_each_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sessions_file: Path
) -> None:
    post, seen = _chat(monkeypatch, tmp_path)
    first = post(_turn(user="default"))
    second = post(_turn(user="default"))
    assert first.status_code == 200 and second.status_code == 200
    assert seen == [None, None]
    assert not sessions_file.exists()
    assert not gateway_sessions._sessions


def test_an_explicit_session_resumes_for_the_same_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sessions_file: Path
) -> None:
    post, seen = _chat(monkeypatch, tmp_path)
    headers = {"X-Bridge-Session": "conv-1"}
    assert post(_turn(user="default"), headers=headers).status_code == 200
    assert post(_turn(user="other"), headers=headers).status_code == 200
    assert seen == [None, "resume-1"]
    text = sessions_file.read_text(encoding="utf-8")
    assert CLIENT not in text
    assert f"claude|{_digest(CLIENT)}|conv-1" in text


def test_the_same_session_id_does_not_cross_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sessions_file: Path
) -> None:
    post, seen = _chat(monkeypatch, tmp_path)
    headers = {"X-Bridge-Session": "conv-1"}
    assert post(_turn(), token=CLIENT, headers=headers).status_code == 200
    assert post(_turn(), token=OWNER, headers=headers).status_code == 200
    assert post(_turn(), token=CLIENT, headers=headers).status_code == 200
    assert seen == [None, None, "resume-1"]
    stored = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert set(stored) == {
        f"claude|{_digest(CLIENT)}|conv-1",
        f"claude|{_digest(OWNER)}|conv-1",
    }
    assert CLIENT not in sessions_file.read_text(encoding="utf-8")
    assert OWNER not in sessions_file.read_text(encoding="utf-8")


def test_bridge_session_resumes_and_a_failed_save_still_returns_200(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    post, seen = _chat(monkeypatch, tmp_path)
    assert post(_turn(session="s1")).status_code == 200
    assert post(_turn(user="default", session="s1")).status_code == 200
    assert seen == [None, "resume-1"]

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(gateway_sessions.gateway_auth, "write_private", boom)
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway_sessions"):
        response = post(_turn(session="s2"))
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"
    assert "could not save the sessions file" in caplog.text


def test_user_field_resumes_when_it_is_not_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    post, seen = _chat(monkeypatch, tmp_path)
    assert post(_turn(user="conv-9")).status_code == 200
    assert post(_turn(user="conv-9")).status_code == 200
    assert seen == [None, "resume-1"]


def test_the_first_start_beside_the_old_workdir_forgets_its_resume_ids(tmp_path, monkeypatch) -> None:
    """The default workdir left ``<home>/work``: an id made there cannot resume in the new one."""
    from agent_cli_bridge import gateway

    home = tmp_path / ".agent-cli-bridge"
    (home / "work").mkdir(parents=True)
    monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(home))
    monkeypatch.delenv("BRIDGE_WORKDIR", raising=False)
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})
    gateway_sessions._session_put("claude", CLIENT, "chat-1", "old-resume-id")

    assert gateway._workdir() == str(tmp_path / ".agent-cli-bridge-work")
    assert gateway_sessions._session_get("claude", CLIENT, "chat-1") is None

    gateway_sessions._session_put("claude", CLIENT, "chat-1", "new-resume-id")
    gateway._workdir()  # the new workdir exists now: nothing more is forgotten
    assert gateway_sessions._session_get("claude", CLIENT, "chat-1") == "new-resume-id"


def test_a_configured_workdir_inside_the_bridge_home_is_warned_about(tmp_path, monkeypatch, caplog) -> None:
    from agent_cli_bridge import gateway

    home = tmp_path / "home"
    monkeypatch.setenv("AGENT_CLI_BRIDGE_HOME", str(home))
    monkeypatch.setattr(gateway, "_RUNTIME_CONFIG", {})
    monkeypatch.setattr(gateway, "_warned_workdirs", set())
    monkeypatch.setenv("BRIDGE_WORKDIR", str(home / "work"))
    with caplog.at_level(logging.WARNING, logger="agent_cli_bridge.gateway"):
        gateway._workdir()
        gateway._workdir()
        monkeypatch.setenv("BRIDGE_WORKDIR", str(tmp_path / "elsewhere"))
        gateway._workdir()
    warnings = [r.getMessage() for r in caplog.records if "inside the bridge home" in r.getMessage()]
    assert len(warnings) == 1
