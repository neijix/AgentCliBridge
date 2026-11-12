"""Strata: a local model already being served on this machine, for a direct chat.

Strata (a local OpenAI-compatible server, default ``127.0.0.1:8080``) is not a CLI agent. An app
chats with the server the owner already started. This module is what every app shares: whether
that server is up, which model it names, and its loopback URL. It never starts Strata.

``/v1/models`` is an empty list while the engine is not loaded (and idle-unload is off). ``/health``
still names the model and says ``service: strata``, so that is what counts.
"""
import http.client
import json
import os
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .http_get import get_bytes

# Strata's own default, and the context a launch uses when /health has not reported one yet.
DEFAULT_PORT = 8080
DEFAULT_CONTEXT = 32_768
_PROBE_TIMEOUT_SECONDS = 0.4
_PROBE_MAX_BYTES = 65_536
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Serving:
    """One Strata server that answered ``/health`` on this computer."""

    model: str
    base_url: str
    context_tokens: int
    is_loaded: bool


def state_dir(
    environ: dict[str, str] | None = None, *, windows: bool | None = None, home: Path | None = None,
) -> Path:
    """Where Strata keeps per-user state (the same folders as ``strata_control.paths.state_base``)."""
    env = os.environ if environ is None else environ
    is_windows = os.name == "nt" if windows is None else windows
    root = Path.home() if home is None else home
    if is_windows:
        local = env.get("LOCALAPPDATA") or str(root / "AppData" / "Local")
        return Path(local) / "Strata"
    return Path(env.get("XDG_STATE_HOME") or str(root / ".local" / "state")) / "strata"


def _port_number(port: object) -> int | None:
    """A TCP port, or None. A bool is not a port (``True`` is an int)."""
    if isinstance(port, bool) or not isinstance(port, int | str):
        return None
    try:
        number = int(port)
    except ValueError:
        return None
    if not 0 < number < 65536:
        return None
    return number


def _loopback_base(host: str, port: object) -> str | None:
    """``http://127.0.0.1:<port>`` for a loopback host, else None (a LAN address is never used)."""
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    number = _port_number(port)
    if host not in _LOOPBACK or number is None:
        return None
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{number}"


def _base_from_url(url: object) -> str | None:
    """A loopback ``api_url`` from a ready file, or None."""
    if not isinstance(url, str) or not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme != "http" or not parts.hostname:
        return None
    path = parts.path.rstrip("/")
    if path not in ("", "/v1"):
        return None
    return _loopback_base(parts.hostname, parts.port)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _add(found: list[str], url: str | None) -> None:
    if url and url not in found:
        found.append(url)


def candidate_bases(state: Path | None = None) -> list[str]:
    """Loopback URLs worth probing: ready files, launch configs, then the default port."""
    root = state_dir() if state is None else state
    found: list[str] = []
    runtime = root / "runtime"
    if runtime.is_dir():
        for path in sorted(runtime.glob("*.ready.json")):
            data = _read_json(path) or {}
            _add(found, _base_from_url(data.get("api_url")) or _loopback_base("127.0.0.1", data.get("bound_port")))
    launch = root / "launch"
    if launch.is_dir():
        for path in sorted(launch.glob("*.json")):
            if path.name.endswith(".choices.json"):
                continue
            data = _read_json(path) or {}
            _add(found, _loopback_base(str(data.get("host") or "127.0.0.1"), data.get("port")))
    _add(found, _loopback_base("127.0.0.1", DEFAULT_PORT))
    return found


def _get_json(url: str) -> Any:
    try:
        body = get_bytes(url, _PROBE_MAX_BYTES, timeout=_PROBE_TIMEOUT_SECONDS)
        return json.loads(body.decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        return None


def _context_tokens(health: dict[str, Any]) -> int:
    ctx = health.get("max_context")
    if isinstance(ctx, int) and not isinstance(ctx, bool) and ctx > 0:
        return ctx
    return DEFAULT_CONTEXT


def probe(base: str) -> Serving | None:
    """The model ``/health`` names on ``base``, or None when that port is not Strata.

    A server whose engine is not loaded still counts: ``/health`` names the model while
    ``/v1/models`` stays empty, and the first chat request loads the weights.
    """
    health = _get_json(f"{base.rstrip('/')}/health")
    if not isinstance(health, dict) or health.get("status") != "ok" or health.get("service") != "strata":
        return None
    model = health.get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    return Serving(
        model=model.strip(),
        base_url=base.rstrip("/"),
        context_tokens=_context_tokens(health),
        is_loaded=health.get("loaded") is True,
    )


def discover(state: Path | None = None) -> list[Serving]:
    """Strata servers answering on this computer, one per model id. Empty when none are up."""
    found: list[Serving] = []
    seen: set[str] = set()
    for base in candidate_bases(state):
        serving = probe(base)
        if serving is None or serving.model in seen:
            continue
        seen.add(serving.model)
        found.append(serving)
    return found


def serving_for(model: str, state: Path | None = None) -> Serving | None:
    """The server for ``model``, or the only one running when ``model`` is empty. None if none match."""
    found = discover(state)
    if not found:
        return None
    wanted = model.strip()
    if not wanted:
        return found[0]
    return next((item for item in found if item.model == wanted), None)
