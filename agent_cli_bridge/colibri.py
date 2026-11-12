"""colibri (github.com/JustVugg/colibri): a model served on this machine, for a direct chat.

colibri is a local inference engine with an OpenAI-compatible server (``coli start``, on
127.0.0.1:8000 by default). It is not a CLI agent: an app chats with that server itself, with no
tools (an agent CLI's own prompt, ~16k tokens of tool schemas, takes hours to read on a CPU).
This module is what every app shares: whether ``coli setup`` has finished (``setup.json`` says
``ready``), which model it installed, and the server's URL and model id, starting the configured
server first when colibri does not answer on its port.
"""
import http.client
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any

from .http_get import get_bytes
from .processes import background_process_options

logger = logging.getLogger(__name__)

# Loading the weights of a several-hundred-billion-parameter model takes a while.
START_TIMEOUT_SECONDS = 300.0
_PROBE_TIMEOUT_SECONDS = 3.0
# colibri serves GLM with a 4096-token context unless told otherwise: a chat that carries its
# earlier turns outgrows that quickly. A server the bridge starts gets this much; a `CTX` the
# owner set wins.
CONTEXT_TOKENS = 32_768
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_start_lock = threading.Lock()  # two turns on a stopped server start it once
# health and /v1/models are one small JSON document. The shared GET skips the proxy on loopback.
_PROBE_MAX_BYTES = 1024 * 1024


def setup_home() -> Path:
    """Where ``coli setup`` keeps ``setup.json`` (the same rules as colibri's ``setup_flow``)."""
    explicit = os.environ.get("COLI_SETUP_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "colibri"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "colibri"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "colibri"


def load_setup() -> dict[str, Any] | None:
    """colibri's ``setup.json`` when it describes a finished install, else None.

    A download still running (``"status": "pending"``), a missing launcher or a file that is not
    JSON all mean "not installed": the agent is not offered.
    """
    try:
        config = json.loads((setup_home() / "setup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or config.get("status") != "ready":
        return None
    launcher = config.get("launcher")
    if not isinstance(launcher, str) or not Path(launcher).is_file():
        return None
    return config


def model_ids(config: dict[str, Any]) -> list[str]:
    """The picker's list: the model ``coli setup`` installed (its catalog id, e.g. ``glm-5.3``)."""
    found = config.get("model")
    model = found if isinstance(found, dict) else {}
    model_id = model.get("id") or config.get("family")
    return [str(model_id)] if model_id else []


def base_url(config: dict[str, Any]) -> str:
    """The server's OpenAI-compatible root on loopback (a wildcard bind is reached there).

    Raises RuntimeError for another host (the project's code never leaves this machine) or a
    port that is not a number in 1-65535.
    """
    host = str(config.get("host") or "127.0.0.1")
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if host not in _LOOPBACK:
        raise RuntimeError(f"colibri is set up on {host}; only a server on this machine is used")
    if ":" in host:
        host = f"[{host}]"
    try:
        port = int(config.get("port") or 8000)
    except (TypeError, ValueError):
        port = 0
    if not 0 < port < 65536:
        raise RuntimeError(f"colibri's setup names the port {config.get('port')!r}, which is not a port number")
    return f"http://{host}:{port}/v1"


def _get_json(url: str) -> Any:
    try:
        body = get_bytes(url, _PROBE_MAX_BYTES, timeout=_PROBE_TIMEOUT_SECONDS)
        return json.loads(body.decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        return None


def served_model(url: str) -> str | None:
    """The id colibri answers to on ``url``, or None when colibri is not up there.

    colibri rejects any other model id with a 404, and its id (``glm-5.2-colibri``) is not the
    catalog's, so it is read from the server. Only colibri counts: its ``/health`` says ``ok``
    and its models are ``owned_by: colibri`` — another server on the same port (vLLM also
    defaults to 8000) never gets the turn.
    """
    health = _get_json(f"{url.removesuffix('/v1')}/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        return None
    body = _get_json(f"{url}/models")
    data = body.get("data") if isinstance(body, dict) else None
    for entry in data if isinstance(data, list) else ():
        if isinstance(entry, dict) and entry.get("id") and entry.get("owned_by") == "colibri":
            return str(entry["id"])
    return None


def start_server(config: dict[str, Any]) -> None:
    """``coli start --background``: the server ``coli setup`` configured, in its own process.

    Raises RuntimeError when it cannot start: no launcher in the setup, a launcher that will not
    run, a start that takes over two minutes, or one that exits non-zero.
    """
    launcher = config.get("launcher")
    if not isinstance(launcher, str) or not launcher:
        raise RuntimeError("colibri's setup names no launcher; run `coli setup` again")
    argv = [sys.executable, launcher, "start", "--background", "--json", "--no-browser"]
    env = dict(os.environ)
    env.setdefault("CTX", str(CONTEXT_TOKENS))
    logger.info("starting colibri: %s", argv)
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=120, env=env, stdin=subprocess.DEVNULL,
            cwd=str(Path(launcher).parent), **background_process_options(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("`coli start` did not return within 120s") from exc
    except OSError as exc:
        raise RuntimeError(f"could not run `coli start`: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-400:]
        raise RuntimeError(f"`coli start` exited with status {completed.returncode}: {detail}")


def ensure_served_model(config: dict[str, Any], timeout: float = START_TIMEOUT_SECONDS) -> tuple[str, str]:
    """``(base URL, served model id)``, starting the server and waiting for it when it is down.

    Raises RuntimeError with a message for the owner when it cannot be reached.
    """
    url = base_url(config)
    served = served_model(url)
    if served:
        return url, served
    with _start_lock:
        served = served_model(url)  # another turn started it meanwhile
        if served:
            return url, served
        start_server(config)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # `coli start` moves to the next free port when another program holds this one.
            url = base_url(load_setup() or config)
            served = served_model(url)
            if served:
                return url, served
            time.sleep(2.0)
    raise RuntimeError(f"colibri did not answer on {url} within {int(timeout)}s after `coli start`")


def model_name(config: dict[str, Any]) -> str:
    """The installed model's display name (``GLM-5.3``). colibri's server calls every GLM it
    serves ``glm-5.2-colibri``, so this is the name to show, not the served id."""
    found = config.get("model")
    model = found if isinstance(found, dict) else {}
    return str(model.get("name") or model.get("id") or config.get("family") or "colibri")
