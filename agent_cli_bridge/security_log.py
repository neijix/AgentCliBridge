"""SecurityLog: a durable record of every security stop a turn hit.

``run_agent`` writes one JSON line per stop, so the owner can review later what was flagged
and where it came from (the gateway serves it at ``GET /security``):

- ``injection_detected`` — the InjectionGuard flagged a tool's output (the turn is tainted).
- ``action_blocked`` — the guard denied a tool approval on a tainted turn.
- ``page_withheld`` — D3SKWEBSCOUT withheld a page it rated ``injection_risk`` high.

Each entry carries the page or resource the stop is about (``url``) when the tool call named
one, so the log links back to it, and an ``id``: ``entry_url(id)`` opens that entry on the
gateway's page, and the ``InjectionDetected`` / ``ActionBlocked`` events carry it as
``details_url`` so a host can link its own warning to the details. The file lives next to the gateway's ``sessions.json`` under the bridge home
(``$AGENT_CLI_BRIDGE_HOME``, or ``~/.agent-cli-bridge``), named ``security-log.jsonl``.
``$AGENT_CLI_BRIDGE_SECURITY_LOG`` points it elsewhere, or turns it off with ``off``. Every turn
on this machine shares it, whichever host ran the turn. Writing is best effort: a log that
cannot be written never breaks a turn. Command text is stored with token values redacted.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import gateway_auth
from .events import ActionBlocked, InjectionDetected, StreamEvent, ToolCall, ToolResult
from .web_scout import fetch_url, is_fetch_call

log = logging.getLogger(__name__)

ENV_VAR = "AGENT_CLI_BRIDGE_SECURITY_LOG"
GATEWAY_URL_VAR = "AGENT_CLI_BRIDGE_URL"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:4747"
DISABLED_VALUES = frozenset({"off", "none", "0", "false"})
MAX_BYTES = 2_000_000  # the live file rolls over to ``.1`` past this size
MAX_TEXT = 600

INJECTION_DETECTED = "injection_detected"
ACTION_BLOCKED = "action_blocked"
PAGE_WITHHELD = "page_withheld"
KINDS = (INJECTION_DETECTED, ACTION_BLOCKED, PAGE_WITHHELD)

_URL_KEYS = ("url", "uri", "href", "link", "page_url", "source_url")
_TARGET_KEYS = ("query", "q", "file_path", "path", "command", "pattern")
_PASSAGE_KEYS = ("flagged_passages", "flagged", "passages", "findings", "reasons")
_TOKEN_ENV_KEYS = ("BRIDGE_TOKEN", "BRIDGE_OWNER_TOKEN")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_TOKEN_ASSIGN_RE = re.compile(
    r"(?i)((?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|token)\s*[=:]\s*)[^\s&\"']{8,}"
)
_write_lock = threading.Lock()


def default_path(env: dict[str, str] | None = None) -> Path | None:
    """``$AGENT_CLI_BRIDGE_SECURITY_LOG`` when set (None when it says off), else the home file.

    Passing an env mapping only names the path. The home directory is created when the
    process environment is used, which is the log this machine actually writes.
    """
    values = os.environ if env is None else env
    explicit = values.get(ENV_VAR, "").strip()
    if explicit.lower() in DISABLED_VALUES:
        return None
    if explicit:
        return Path(explicit).expanduser()
    if env is None:
        return gateway_auth.bridge_home() / "security-log.jsonl"
    return gateway_auth.bridge_home_path(values) / "security-log.jsonl"


def _redact(text: str) -> str:
    """Drop token values: this process's bridge tokens, bearer tokens, and token assignments."""
    for key in _TOKEN_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if len(value) >= 8 and value in text:
            text = text.replace(value, "[redacted]")
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    return _TOKEN_ASSIGN_RE.sub(r"\1[redacted]", text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {_redact(str(key)): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def entry_url(entry_id: str, env: dict[str, str] | None = None) -> str:
    """The gateway page showing one entry (``$AGENT_CLI_BRIDGE_URL`` when the gateway moved)."""
    values = os.environ if env is None else env
    base = (values.get(GATEWAY_URL_VAR, "").strip() or DEFAULT_GATEWAY_URL).rstrip("/")
    return f"{base}/security#e-{entry_id}"


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    text = _redact(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _first_str(mapping: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def withheld_page(output: str) -> dict[str, Any] | None:
    """What a scout ``fetch`` result says about a withheld page; None when the page came back.

    Reads the scout's JSON envelope (``withheld`` / ``injection_risk``), with a text fallback
    for a result that is not plain JSON.
    """
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        risk = data.get("injection_risk")
        risk = risk.get("level") if isinstance(risk, dict) else risk
        if not (data.get("withheld") is True or str(risk).lower() == "high"):
            return None
        passages: list[str] = []
        for key in _PASSAGE_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                passages = [_clip(p, 300) for p in value[:5]]
                break
            if isinstance(value, str) and value.strip():
                passages = [_clip(value, 300)]
                break
        return {"url": _first_str(data, _URL_KEYS), "passages": passages, "risk": str(risk or "high")}
    lowered = (output or "").lower()
    if '"withheld": true' in lowered or '"injection_risk": "high"' in lowered:
        return {"url": "", "passages": [_clip(output, 300)], "risk": "high"}
    return None


class SecurityLog:
    """Where security stops are written; ``run_agent`` builds one unless the host passes its own or False.

    - ``path`` — the JSON-lines file (default: ``default_path()``; None writes nothing).
    - ``source`` — which host ran the turn, so the log tells them apart.
    """

    def __init__(self, path: Path | str | None = None, *, source: str = "agent-cli-bridge") -> None:
        self.path = Path(path) if path is not None else default_path()
        self.source = source

    def record(self, entry: dict[str, Any]) -> str:
        """Append one entry; its id, or "" when nothing was written."""
        if self.path is None:
            return ""
        redacted = _redact_value(entry)
        if not isinstance(redacted, dict):
            return ""
        entry_id = uuid.uuid4().hex[:12]
        line = json.dumps(
            {"id": entry_id, "ts": time.time(), "source": self.source, **redacted}, ensure_ascii=False
        )
        try:
            with _write_lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                    self.path.replace(self.path.with_name(self.path.name + ".1"))
                gateway_auth.append_private(self.path, line + "\n")
        except OSError as exc:
            log.warning("security log not written to %s: %s", self.path, exc)
            return ""
        return entry_id

    def entries(self, limit: int = 500) -> list[dict[str, Any]]:
        """The latest entries, newest first (the rolled-over file included)."""
        if self.path is None:
            return []
        lines: list[str] = []
        for path in (self.path.with_name(self.path.name + ".1"), self.path):
            try:
                lines.extend(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                continue
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
            if len(out) >= limit:
                break
        return out

    def clear(self) -> None:
        if self.path is None:
            return
        with _write_lock:
            for path in (self.path, self.path.with_name(self.path.name + ".1")):
                path.unlink(missing_ok=True)

    def turn(self, *, command: str, model: str | None, cwd: str | None) -> "TurnRecorder":
        return TurnRecorder(self, {"command": command, "model": model or "", "cwd": cwd or ""})


class TurnRecorder:
    """One turn's view of the log: remembers tool calls so a stop links to what they touched."""

    def __init__(self, security_log: SecurityLog, context: dict[str, str]) -> None:
        self.log = security_log
        self.context = context
        self._calls: dict[str, ToolCall] = {}
        self._tainted_by = ""  # the page that tainted the turn, for the blocks that follow

    def _call_fields(self, call_id: str, name: str = "", arguments: Any = None) -> dict[str, Any]:
        call = self._calls.get(call_id)
        if arguments is None and call is not None:
            arguments = call.arguments
        url = _first_str(arguments, _URL_KEYS)
        if not url and isinstance(arguments, dict):  # a shell ``d3skwebscout fetch <url>``
            url = fetch_url(str(arguments.get("command") or ""))
        return {
            "tool": name or (call.name if call else "tool"),
            "url": url,
            "target": _clip(_first_str(arguments, _TARGET_KEYS), 300),
            "arguments": _clip(arguments, 400) if arguments is not None else "",
        }

    def observe(self, event: StreamEvent) -> None:
        """Remember tool calls; record a scout ``fetch`` that came back withheld."""
        if isinstance(event, ToolCall):
            self._calls[event.call_id] = event
            return
        if not isinstance(event, ToolResult):
            return
        call = self._calls.get(event.call_id)
        if call is None or not is_fetch_call(call.name, call.arguments):
            return
        page = withheld_page(event.output)
        if page is None and event.raw:
            page = withheld_page(event.raw)
        if page is None:
            return
        fields = self._call_fields(event.call_id)
        self.log.record({
            **self.context, **fields, "kind": PAGE_WITHHELD,
            "url": page["url"] or fields["url"], "rules": [f"injection_risk:{page['risk']}"],
            "excerpt": "\n".join(page["passages"]),
        })

    def detected(self, detection: InjectionDetected) -> InjectionDetected:
        """Record a detection; the event again, with ``details_url`` when it was logged."""
        fields = self._call_fields(detection.call_id, detection.tool_name)
        self._tainted_by = self._tainted_by or fields["url"]
        entry_id = self.log.record({
            **self.context, **fields,
            "kind": INJECTION_DETECTED, "rules": list(detection.rules), "excerpt": _clip(detection.excerpt),
        })
        return replace(detection, details_url=entry_url(entry_id)) if entry_id else detection

    def blocked(self, blocked: ActionBlocked) -> ActionBlocked:
        """Record a blocked action; the event again, with ``details_url`` when it was logged."""
        entry_id = self.log.record({
            **self.context, **self._call_fields(blocked.call_id, blocked.name, blocked.arguments),
            "kind": ACTION_BLOCKED, "rules": [], "excerpt": "", "reason": blocked.reason,
            "tainted_by": self._tainted_by,
        })
        return replace(blocked, details_url=entry_url(entry_id)) if entry_id else blocked
