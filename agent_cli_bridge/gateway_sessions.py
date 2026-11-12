"""Resume ids for CLI ``--resume``, durable across gateway restarts.

The on-disk key is ``command|sha256|session_id``: hex SHA-256 of the bearer token, never the
token itself. Loaded on first use. Import must not read sessions.json: that file lives in the
bridge home, and a test (or a relocated home) has to be able to point elsewhere before any read.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import gateway_auth

log = logging.getLogger(__name__)

_MAX_SESSIONS = 256
# The id is part of the on-disk key ``command|sha256|id`` (split on "|") and of a log line.
SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SESSION_HEADER = "x-bridge-session"
# command, token digest, caller session id → the CLI's resume id
_sessions: OrderedDict[tuple[str, str, str], str] = OrderedDict()
_sessions_loaded = False


def explicit_session_id(body: Mapping[str, Any], headers: Any) -> str | None:
    """The resume key: ``bridge.session``, else ``X-Bridge-Session``, else ``user``.

    The OpenAI ``user`` field counts only when it is a non-empty string and not the literal
    ``default`` and a valid id; an odd ``user`` (an email, a long name) is no session. A header
    or ``bridge.session`` of ``default`` is still explicit, and is returned as sent, valid or not:
    the route refuses an invalid one with ``is_valid_session_id``.
    """
    bridge = body.get("bridge")
    if isinstance(bridge, Mapping):
        session = _nonempty_text(bridge.get("session"))
        if session is not None:
            return session
    header = _header_session(headers)
    if header is not None:
        return header
    user = body.get("user")
    if isinstance(user, str) and user != "default" and is_valid_session_id(user):
        return user
    return None


def is_valid_session_id(session_id: str) -> bool:
    """True for 1 to 128 characters of ``A-Z a-z 0-9 . _ -``."""
    return SESSION_ID.fullmatch(session_id) is not None


def _nonempty_text(value: object) -> str | None:
    if not value:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _header_session(headers: Any) -> str | None:
    if headers is None:
        return None
    try:
        pairs = headers.items()
    except AttributeError:
        return None
    for key, value in pairs:
        if str(key).lower() == _SESSION_HEADER:
            text = _nonempty_text(value)
            if text is not None:
                return text
    return None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _store_key(
    command: str, token: str | None, session_id: str | None
) -> tuple[str, str, str] | None:
    if not command or not token or not session_id:
        return None
    return (command, _token_digest(token), session_id)


def _sessions_file() -> Path:
    return gateway_auth.bridge_home() / "sessions.json"


def _ensure_sessions_loaded() -> None:
    global _sessions_loaded
    if _sessions_loaded:
        return
    _sessions_loaded = True
    _load_sessions()


def _parse_stored_key(compound: object) -> tuple[str, str, str] | None:
    """``command|sha256|session_id``, or None when the entry is not those three fields."""
    parts = str(compound).split("|")
    if len(parts) != 3:
        return None
    command, digest, session_id = parts
    if not command or not digest or not session_id:
        return None
    return command, digest, session_id


def _load_sessions() -> None:
    """Best-effort restore. A non-object file is logged and leaves the map empty."""
    path = _sessions_file()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("sessions file %s could not be read: %s", path, exc)
        return
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        log.warning("sessions file %s is not a JSON object; ignoring it", path)
        return
    if not isinstance(raw, dict):
        log.warning("sessions file %s is not a JSON object; ignoring it", path)
        return
    for compound, resume_id in raw.items():
        parsed = _parse_stored_key(compound)
        if parsed is not None and isinstance(resume_id, str):
            _sessions[parsed] = resume_id


def _save_sessions() -> None:
    """Best-effort persist; a failure is logged and does not propagate."""
    try:
        path = _sessions_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            f"{command}|{digest}|{session_id}": rid
            for (command, digest, session_id), rid in _sessions.items()
        }
        tmp = path.with_suffix(".json.tmp")
        gateway_auth.write_private(tmp, json.dumps(payload))
        tmp.replace(path)
    except Exception:
        log.warning("could not save the sessions file", exc_info=True)


def _session_get(command: str, token: str | None, session_id: str | None) -> str | None:
    key = _store_key(command, token, session_id)
    if key is None:
        return None
    _ensure_sessions_loaded()
    return _sessions.get(key)


def _resume_lookup(command: str, session_id: str | None, headers: Any) -> tuple[str, str | None]:
    """Bearer token and the CLI resume id stored for this caller session."""
    token = gateway_auth.bearer_token(headers.get("authorization"))
    return token, _session_get(command, token, session_id)


def _session_put(
    command: str, token: str | None, session_id: str | None, resume_id: str
) -> None:
    key = _store_key(command, token, session_id)
    if key is None:
        return
    _ensure_sessions_loaded()
    _sessions[key] = resume_id
    _sessions.move_to_end(key)
    while len(_sessions) > _MAX_SESSIONS:
        _sessions.popitem(last=False)
    _save_sessions()


def forget_all(reason: str) -> None:
    """Drop every stored resume id, once none of them can resume any more."""
    _ensure_sessions_loaded()
    if not _sessions:
        return
    log.warning("forgetting %d stored resume id(s): %s", len(_sessions), reason)
    _sessions.clear()
    _save_sessions()


def _session_count() -> int:
    _ensure_sessions_loaded()
    return len(_sessions)
