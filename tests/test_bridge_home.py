"""The suite must not create or read the owner's real ``~/.agent-cli-bridge``."""
import ast
import builtins
import io
import json
import os
import sys
from pathlib import Path

import pytest

_REAL = Path.home() / ".agent-cli-bridge"
_GATEWAY_SOURCE = Path(__file__).resolve().parents[1] / "agent_cli_bridge" / "gateway.py"


def _under_real(path: object) -> bool:
    try:
        text = os.fspath(path)  # type: ignore[arg-type]
    except TypeError:
        return False
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    text = os.path.abspath(text)
    real = os.path.abspath(_REAL)
    return text == real or text.startswith(real + os.sep)


def _exists(lstat, path: Path) -> bool:
    try:
        lstat(path)
    except FileNotFoundError:
        return False
    return True


def _loads_sessions_at_import() -> bool:
    tree = ast.parse(_GATEWAY_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if isinstance(func, ast.Name) and func.id == "_load_sessions":
            return True
    return False


def _install_guard(monkeypatch: pytest.MonkeyPatch, hits: list[str]) -> None:
    def note(path: object) -> None:
        if _under_real(path):
            hits.append(os.fspath(path) if not isinstance(path, int) else str(path))

    def wrap(original):
        def wrapped(path, *args, **kwargs):
            note(path)
            return original(path, *args, **kwargs)

        return wrapped

    def wrap_replace(original):
        def wrapped(src, dst, *args, **kwargs):
            note(src)
            note(dst)
            return original(src, dst, *args, **kwargs)

        return wrapped

    monkeypatch.setattr(builtins, "open", wrap(builtins.open))
    monkeypatch.setattr(io, "open", wrap(io.open))
    monkeypatch.setattr(os, "open", wrap(os.open))
    monkeypatch.setattr(os, "stat", wrap(os.stat))
    monkeypatch.setattr(os, "lstat", wrap(os.lstat))
    monkeypatch.setattr(os, "listdir", wrap(os.listdir))
    monkeypatch.setattr(os, "mkdir", wrap(os.mkdir))
    monkeypatch.setattr(os, "makedirs", wrap(os.makedirs))
    monkeypatch.setattr(os, "chmod", wrap(os.chmod))
    monkeypatch.setattr(os, "replace", wrap_replace(os.replace))


def _exercise() -> None:
    import agent_cli_bridge.gateway as gateway
    import agent_cli_bridge.gateway_auth as gateway_auth
    import agent_cli_bridge.security_log as security_log

    assert not _under_real(gateway_auth.bridge_home())
    filtered = {
        key: value for key, value in os.environ.items() if key != "AGENT_CLI_BRIDGE_SECURITY_LOG"
    }
    log_path = security_log.default_path(filtered)
    assert log_path is not None and not _under_real(log_path)
    assert not _under_real(gateway._sessions_file())
    assert not _under_real(gateway._workdir())
    gateway_auth.load_token("ACB_BRIDGE_HOME_UNTOUCHED", gateway_auth.TOKEN_FILE)
    assert ("claude", "sentinel-session") not in gateway._sessions


def _drop_sentinel() -> None:
    gateway = sys.modules.get("agent_cli_bridge.gateway")
    if gateway is None:
        return
    gateway._sessions.pop(("claude", "sentinel-session"), None)
    gateway._sessions_loaded = False


def test_suite_leaves_real_home_untouched(monkeypatch):
    home = os.environ.get("AGENT_CLI_BRIDGE_HOME", "")
    work = os.environ.get("BRIDGE_WORKDIR", "")
    assert home and not _under_real(home)
    assert work and not _under_real(work)
    assert not _loads_sessions_at_import()
    sessions = Path(home) / "sessions.json"
    sessions.write_text(
        json.dumps({"claude|sentinel-session": "resume-sentinel"}), encoding="utf-8"
    )
    existed = _REAL.exists()
    real_lstat = os.lstat
    hits: list[str] = []
    _install_guard(monkeypatch, hits)
    try:
        _exercise()
        assert hits == []
        assert _exists(real_lstat, _REAL) == existed
    finally:
        sessions.unlink(missing_ok=True)
        _drop_sentinel()
