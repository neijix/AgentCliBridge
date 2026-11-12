"""OpenAI-compatible local gateway over the CLI bridge (+ passthrough).

Exposes the AI coding CLIs you already pay for as a plain OpenAI-style API on
127.0.0.1, so ANY app (any language) can use them as chat models:

    POST /v1/chat/completions   {"model": "claude:sonnet", "messages": [...]}
    POST /browser/v1/chat/completions   the same for a browser assistant (Brave Leo):
                                Claude only, every tool off, no ``bridge`` object
    GET  /v1/models             CLI models + upstream (e.g. local-model server) models
    GET  /health
    GET  /security              security stops (injections, blocked actions, withheld pages)

Model id scheme: ``<command>:<model>`` (e.g. ``claude:sonnet``,
``cursor:composer-2.5``, ``gemini:gemini-2.5-flash``, ``copilot:auto``) or the
bare command for the spec's default model. Any other id is proxied verbatim to
the upstream OpenAI server (``BRIDGE_UPSTREAM_OPENAI``, default
``http://127.0.0.1:8899/v1``, e.g. a local MLX/Ollama/llama.cpp server) — one endpoint for CLIs and local models alike.

Multi-turn: stateless clients get the conversation inlined as a transcript.
An explicit session (``bridge.session``, else ``X-Bridge-Session``, else
``user`` other than ``default``) resumes via --resume. The id is stored
under a hash of the bearer token, never the token itself.

Env:
    PORT                     listen port (default 4747, fixed — see .env.example)
    BRIDGE_UPSTREAM_OPENAI   upstream OpenAI base (default http://127.0.0.1:8899/v1)
    BRIDGE_PERMISSION_MODE   CLI permission mode (default plan — read-only;
                             set acceptEdits for agentic use)
    BRIDGE_WORKDIR           cwd the CLIs run in (default: <bridge home>-work, a sibling of
                             the bridge home, never inside it)
    BRIDGE_WEB_SCOUT         ``0``, ``off`` or ``false`` (any case) disables WebScout on a
                             gateway turn; a missing checkout logs once and that turn has
                             no web tools

Access: every request must name this machine in ``Host``, come from no page or a
page on this machine (``Origin``), and carry ``Authorization: Bearer <token>``;
write-capable permission modes, a ``bridge.cwd`` outside the configured workdir,
``bridge.env``, ``bridge.cli_args`` and the admin routes need the owner token
(``gateway_auth.owner_only_options``).

Compliance: local single-user bridge over official CLI binaries and the
user's own logins — never expose this beyond loopback or share it as a
service (see README.md).
"""
import logging
import os
import re
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__, gateway_auth, gateway_sessions, upstream
from .argv import PERMISSION_MODES
from .events import Completed, SessionUpdate, StreamError, TextDelta  # noqa: F401 (tests fake these)
from .gateway_openai import (
    _error_json,
    _json_object,
    _no_user_message,
    _turn_response,
    render_transcript,
)
from .runner import run_agent
from .security_log import KINDS, SecurityLog
from .specs import CLI_AGENT_SPECS, CliAgentSpec, cli_agent_spec, resolve_binary
from .upstream import MODEL_PREFIX as UPSTREAM_COMMAND
from .web_scout import web_scout_for_gateway
from .webui import PAGE, SECURITY_PAGE

_sessions = gateway_sessions._sessions
_sessions_file = gateway_sessions._sessions_file

log = logging.getLogger(__name__)

DEFAULT_PORT = 4747
DEFAULT_UPSTREAM = "http://127.0.0.1:8899/v1"
DEFAULT_PERMISSION_MODE = "plan"  # read-leaning: an API backend must not edit unless opted in

START_TIME = time.time()

app = FastAPI(title="AgentCliBridge Gateway", docs_url=None, redoc_url=None)

# Static pages: no data in them, and they ask for the token before calling the API.
PUBLIC_PAGES = frozenset({"/", "/security"})
# The pages hold the owner token's input: no other page may frame them (clickjacking).
PAGE_HEADERS = {"Content-Security-Policy": "frame-ancestors 'none'", "X-Frame-Options": "DENY"}


class LocalCallerGuard:
    """Host and Origin on this machine, then a bearer token (see gateway_auth).

    Plain ASGI, not ``@app.middleware("http")``: a streamed turn's response and its client
    disconnect (which kills the CLI's process group) pass through untouched.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        refusal = self._refusal(request)
        if refusal is not None:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _refusal(request: Request) -> JSONResponse | None:
        if not gateway_auth.is_local_host(request.headers.get("host")):
            return JSONResponse(
                _error_json("Host must be this machine (localhost or 127.0.0.1)", "forbidden_host"),
                status_code=403,
            )
        if not gateway_auth.is_local_origin(request.headers.get("origin"), request.headers.get("host")):
            return JSONResponse(
                _error_json("Only the gateway's own page may call this API from a browser", "forbidden_origin"),
                status_code=403,
            )
        if request.method in ("GET", "HEAD") and request.url.path in PUBLIC_PAGES:
            return None
        try:
            role = gateway_auth.caller_role(request.headers.get("authorization"))
        except OSError as exc:
            return JSONResponse(
                _error_json(f"Could not read the gateway tokens: {exc}", "token_unavailable"),
                status_code=500,
            )
        if role is None:
            return JSONResponse(
                _error_json(
                    "Send Authorization: Bearer <token> (~/.agent-cli-bridge/gateway-token)",
                    "unauthorized",
                ),
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.caller_role = role  # lands in scope["state"], seen by the route's Request
        return None


app.add_middleware(LocalCallerGuard)


def _is_owner(request: Request) -> bool:
    return getattr(request.state, "caller_role", None) == "owner"


def _owner_required(what: str) -> JSONResponse:
    return JSONResponse(
        _error_json(f"{what} needs the owner token (~/.agent-cli-bridge/gateway-owner-token)",
                    "owner_token_required"),
        status_code=403,
    )

# Runtime config overrides set from the web UI (POST /api/config). Layered
# ABOVE env vars so a live change takes effect without a restart; "Apply & save"
# additionally writes the value to .env so it survives one. Keys map to env vars
# via _ENV_KEYS below.
_RUNTIME_CONFIG: dict[str, str] = {}
_ENV_KEYS = {
    "permission_mode": "BRIDGE_PERMISSION_MODE",
    "upstream": "BRIDGE_UPSTREAM_OPENAI",
    "workdir": "BRIDGE_WORKDIR",
}


def _cfg(key: str, env_key: str, default: str) -> str:
    override = _RUNTIME_CONFIG.get(key)
    if override is not None:
        return override
    return os.environ.get(env_key) or default


def _upstream_base() -> str:
    return _cfg("upstream", "BRIDGE_UPSTREAM_OPENAI", DEFAULT_UPSTREAM).rstrip("/")


def _permission_mode() -> str:
    return _cfg("permission_mode", "BRIDGE_PERMISSION_MODE", DEFAULT_PERMISSION_MODE)


def _workdir() -> str:
    configured = _cfg("workdir", "BRIDGE_WORKDIR", "")
    if configured:
        Path(configured).mkdir(parents=True, exist_ok=True)
        _warn_if_inside_bridge_home(configured)
        return configured
    default = gateway_auth.default_workdir()
    if not default.exists() and (gateway_auth.bridge_home_path() / "work").is_dir():
        # The default was <bridge home>/work before 2026-11. A CLI keeps its sessions per
        # working directory, so an id made there would fail to resume on every later turn.
        gateway_sessions.forget_all("the default workdir moved out of the bridge home")
    default.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        default.chmod(0o700)  # mkdir's mode is masked; an existing directory keeps its old mode
    return str(default)


_warned_workdirs: set[str] = set()


def _warn_if_inside_bridge_home(workdir: str) -> None:
    """Once per value: Claude turns deny Read, Edit and Write inside the bridge home."""
    if workdir in _warned_workdirs:
        return
    _warned_workdirs.add(workdir)
    home = gateway_auth.bridge_home_path().expanduser().resolve()
    if Path(workdir).expanduser().resolve().is_relative_to(home):
        log.warning("workdir %s is inside the bridge home %s: Claude turns cannot edit files there", workdir, home)


def _client_workdir() -> str | None:
    """Configured workdir a client cwd must stay inside, or None when nothing set one.

    The runtime override wins over ``BRIDGE_WORKDIR``. This is not ``_workdir()``: that
    falls back to ``gateway_auth.default_workdir()`` and creates the directory. With neither source set,
    every client cwd is refused.
    """
    override = _RUNTIME_CONFIG.get("workdir")
    if override is not None and override.strip():
        return override
    configured = os.environ.get("BRIDGE_WORKDIR", "").strip()
    return configured or None


def _owner_only_for_client(opts: dict[str, Any], flavor: str) -> list[str]:
    return gateway_auth.owner_only_options(opts, flavor, workdir=_client_workdir())


def _current_config() -> dict[str, Any]:
    return {
        "permission_mode": _permission_mode(),
        "upstream": _upstream_base(),
        "workdir": _workdir(),
        "permission_modes": list(PERMISSION_MODES),
    }


def _reject_env_newlines(updates: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise ValueError("A .env value cannot contain a newline")


def _persist_env(updates: dict[str, str]) -> None:
    """Merge ``updates`` into ``.env`` (relative to cwd), preserving other lines.

    The launcher cd's to the repo root before exec'ing the server, so cwd/.env
    is the same file start.sh loads. Existing key lines are rewritten in place;
    unknown keys are appended; comments and blank lines are left untouched.
    A value that contains a newline is refused and nothing is written.
    """
    _reject_env_newlines(updates)
    env_path = Path.cwd() / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n")


# ── model routing ──

# What follows ``flavor:`` goes into the CLI's argv. A real id (``sonnet``, ``claude-opus-5-5[1m]``,
# ``openrouter/stealth/crouton-alpha``, ``gpt-5-mini``) starts with a letter or digit, so no id is a flag.
# A space is one argv item, not a split: the legacy ``Claude Code`` placeholder keeps working.
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/@+\[\]-]{0,127}")

def parse_cli_model(model: str) -> tuple[CliAgentSpec, str | None] | None:
    """Map an OpenAI model id onto (spec, sub_model), or None → upstream proxy.

    ``claude:sonnet`` → (claude spec, "sonnet"); bare ``claude`` → the spec's
    default (first curated model). Unknown prefixes are not CLI routes.
    """
    if not model:
        return None
    command, _, sub = model.partition(":")
    spec = cli_agent_spec(command.strip())
    if spec is None:
        return None
    return spec, sub.strip() or (spec.models[0] if spec.models else None)


def _bad_model_id(sub_model: str | None) -> JSONResponse | None:
    """A 400 for a model id that is not a plain id, so it can never act as a CLI flag."""
    if sub_model is None or MODEL_ID.fullmatch(sub_model):
        return None
    return JSONResponse(
        _error_json("The model id after the colon has characters a model id never has", "bad_request"),
        status_code=400,
    )


# ── per-request bridge extension ──

def parse_bridge_options(
    body: dict[str, Any], headers: Any
) -> tuple[dict[str, Any], str | None]:
    """Extract the optional per-request ``bridge`` object from the body.

    This is what makes the gateway full-fidelity for EVERY consumer app — the
    same knobs an in-process ``run_agent`` integration has, available to any OpenAI
    SDK via ``extra_body={"bridge": {...}}``:

      session          durable --resume key: bridge.session, else the header,
                       else user when it is not the literal "default"
      permission_mode  per-request override of the configured default
      cwd              directory the CLI runs in (must exist)
      env              extra environment overlaid on the server's os.environ
                       (e.g. the caller's own loopback trust channel)
      cli_args         extra argv appended to the CLI invocation

    Returns (options, error_message) — error_message set on invalid input.
    """
    opts: dict[str, Any] = {
        "session": gateway_sessions.explicit_session_id(body, headers),
        "permission_mode": None,
        "cwd": None,
        "env": None,
        "cli_args": None,
    }
    session = opts["session"]
    if session is not None and not gateway_sessions.is_valid_session_id(session):
        return opts, "bridge.session / X-Bridge-Session must be 1 to 128 characters of A-Z a-z 0-9 . _ -"
    raw = body.get("bridge")
    if raw is None:
        return opts, None
    if not isinstance(raw, dict):
        return opts, "bridge must be an object"
    if raw.get("permission_mode") is not None:
        mode = str(raw["permission_mode"]).strip()
        if mode not in PERMISSION_MODES:
            return opts, (
                f"Unknown permission mode {mode!r}; "
                f"expected one of {', '.join(PERMISSION_MODES)}"
            )
        opts["permission_mode"] = mode
    if raw.get("cwd") is not None:
        cwd = str(raw["cwd"])
        if not Path(cwd).is_dir():
            return opts, f"bridge.cwd does not exist: {cwd}"
        opts["cwd"] = cwd
    if raw.get("env") is not None:
        if not isinstance(raw["env"], dict):
            return opts, "bridge.env must be an object of string values"
        opts["env"] = {str(k): str(v) for k, v in raw["env"].items()}
    if raw.get("cli_args") is not None:
        if not isinstance(raw["cli_args"], list):
            return opts, "bridge.cli_args must be an array of strings"
        opts["cli_args"] = [str(a) for a in raw["cli_args"]]
    return opts, None


# ── routes ──

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Human-facing status + configuration page (loopback, single user)."""
    return HTMLResponse(PAGE, headers=PAGE_HEADERS)


@app.get("/security", response_class=HTMLResponse)
async def security_page() -> HTMLResponse:
    """Security stops of every turn on this machine, with links to the pages involved."""
    return HTMLResponse(SECURITY_PAGE, headers=PAGE_HEADERS)


@app.get("/api/security")
async def api_security(request: Request, limit: int = 500, kind: str = ""):
    if not _is_owner(request):
        return _owner_required("Reading the security log")
    security_log = SecurityLog()
    entries = security_log.entries(limit=max(1, min(limit, 5000)))
    if kind:
        entries = [e for e in entries if e.get("kind") == kind]
    return {
        "path": str(security_log.path) if security_log.path else None,
        "kinds": list(KINDS),
        "entries": entries,
    }


@app.delete("/api/security")
async def api_clear_security(request: Request):
    if not _is_owner(request):
        return _owner_required("Clearing the security log")
    SecurityLog().clear()
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    agents = [
        {"command": s.command, "name": s.name, "installed": bool(resolve_binary(s.command))}
        for s in CLI_AGENT_SPECS
    ]
    return {"ok": True, "agents": agents, "upstream": _upstream_base()}


UPSTREAM_NAME = "Local MLX"


async def _probe_upstream() -> dict[str, Any]:
    """Best-effort reachability + model list for the passthrough upstream."""
    base = _upstream_base()
    info: dict[str, Any] = {"url": base, "reachable": False, "models": 0, "model_ids": []}
    entries = await upstream.fetch_models(base)
    if entries is not None:
        info["reachable"] = True
        info["model_ids"] = [m["id"] for m in entries]
        info["models"] = len(entries)
    return info


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    agents = [
        {
            "command": s.command,
            "name": s.name,
            "installed": bool(resolve_binary(s.command)),
            "models": list(s.models),
            "install_hint": s.install_hint,
        }
        for s in CLI_AGENT_SPECS
    ]
    upstream = await _probe_upstream()
    # Surface the passthrough upstream (e.g. a local MLX server) as a first-class agent
    # so pickers can offer it alongside the CLI specs. "installed" tracks live
    # reachability; the loaded model list comes from /v1/models on the upstream.
    agents.append(
        {
            "command": UPSTREAM_COMMAND,
            "name": UPSTREAM_NAME,
            "installed": bool(upstream.get("reachable")),
            "models": list(upstream.get("model_ids") or []),
            "install_hint": (
                ""
                if upstream.get("reachable")
                else f"Start the upstream OpenAI server at {upstream.get('url')}."
            ),
        }
    )
    return {
        "ok": True,
        "version": __version__,
        "port": int(os.environ.get("PORT", DEFAULT_PORT)),
        "uptime_seconds": int(time.time() - START_TIME),
        "sessions": gateway_sessions._session_count(),
        "upstream": upstream,
        "agents": agents,
        "config": _current_config(),
    }


@app.get("/api/config")
async def api_get_config() -> dict[str, Any]:
    return _current_config()


@app.post("/api/config")
async def api_set_config(request: Request):
    # The defaults apply to every client's turns (bypassPermissions included), so only the owner sets them.
    if not _is_owner(request):
        return _owner_required("Changing the gateway's config")
    body = await _json_object(request)
    if isinstance(body, JSONResponse):
        return body

    updates: dict[str, str] = {}
    if "permission_mode" in body:
        mode = str(body["permission_mode"]).strip()
        if mode not in PERMISSION_MODES:
            return JSONResponse(
                _error_json(
                    f"Unknown permission mode {mode!r}; expected one of {', '.join(PERMISSION_MODES)}",
                    "bad_request",
                ),
                status_code=400,
            )
        updates["permission_mode"] = mode
    for key in ("upstream", "workdir"):
        if key in body:
            value = str(body[key]).strip()
            if value:
                updates[key] = value

    env_updates = {_ENV_KEYS[k]: v for k, v in updates.items()}
    if body.get("persist") and env_updates:
        try:
            _reject_env_newlines(env_updates)
        except ValueError as exc:
            return JSONResponse(_error_json(str(exc), "bad_request"), status_code=400)

    _RUNTIME_CONFIG.update(updates)
    if body.get("persist") and env_updates:
        try:
            _persist_env(env_updates)
        except OSError as exc:
            return JSONResponse(
                _error_json(f"Applied, but could not write .env: {exc}", "persist_failed"),
                status_code=500,
            )
    return _current_config()


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    for spec in CLI_AGENT_SPECS:
        if not resolve_binary(spec.command):
            continue
        for m in spec.models:
            data.append(
                {
                    "id": f"{spec.command}:{m}",
                    "object": "model",
                    "created": 0,
                    "owned_by": f"cli/{spec.name}",
                }
            )
    # Merge upstream (local-model server) models, best effort — the gateway stays usable
    # when the upstream is down. Upstream ids are tagged with the synthetic
    # ``mlx:`` prefix so consumers can route them back through this gateway
    # unambiguously. The prefix is removed before the chat request is forwarded.
    for entry in await upstream.fetch_models(_upstream_base()) or []:
        tagged_id = f"{UPSTREAM_COMMAND}:{entry['id']}"
        data.append({**entry, "id": tagged_id, "owned_by": f"cli/{UPSTREAM_NAME}"})
    return {"object": "list", "data": data}


def _run_gateway_agent(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
    """One gateway turn: ``BRIDGE_WEB_SCOUT`` and a missing checkout decide WebScout."""
    kwargs["web_scout"] = web_scout_for_gateway()
    return run_agent(*args, **kwargs)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await _json_object(request)
    if isinstance(body, JSONResponse):
        return body

    model = str(body.get("model") or "")
    route = parse_cli_model(model)
    if route is None:
        return await upstream.proxy_chat(_upstream_base(), body)

    spec, sub_model = route
    if (refusal := _bad_model_id(sub_model)) is not None:
        return refusal
    messages = body.get("messages") or []
    stream = bool(body.get("stream"))
    system_text, prompt = render_transcript(messages)
    if not prompt:
        return _no_user_message()

    bridge_opts, bridge_err = parse_bridge_options(body, request.headers)
    if bridge_err:
        return JSONResponse(_error_json(bridge_err, "bad_request"), status_code=400)
    privileged = _owner_only_for_client(bridge_opts, spec.flavor)
    if privileged and not _is_owner(request):
        return _owner_required(", ".join(privileged))
    session_id = bridge_opts["session"]
    token, resume_id = gateway_sessions._resume_lookup(spec.command, session_id, request.headers)
    if resume_id:
        # CLI-native continuity: only the latest user turn is needed — the
        # CLI's own --resume already carries prior turns. system_text is kept
        # and re-sent (via --append-system-prompt on claude; discarded
        # elsewhere by compose_prompt's resume guard), so callers that
        # rebuild a fresh per-turn system prompt — a host that re-runs
        # retrieval each turn, say — keep it applied. Wiping it here made
        # resumed turns fall back to the CLI's baseline system prompt.
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                _, prompt = render_transcript([m])
                break

    async def events():
        async for ev in _run_gateway_agent(
            spec.command,
            prompt=prompt,
            system_text=system_text,
            model=sub_model,
            permission_mode=bridge_opts["permission_mode"] or _permission_mode(),
            resume_id=resume_id,
            cli_args=bridge_opts["cli_args"],
            cwd=bridge_opts["cwd"] or _workdir(),
            extra_env=bridge_opts["env"],
            security_log=SecurityLog(source="gateway"),
        ):
            yield ev

    return await _turn_response(
        model, events(), request=request, stream=stream, command=spec.command, token=token,
        session_id=session_id,
    )


# A browser assistant's messages carry the open page's text, which anyone on the web wrote.
# Only Claude can run with no tool at all: no built-in tool, no MCP server, no WebScout.
BROWSER_FLAVORS = frozenset({"claude"})
# --no-session-persistence: the page text is not saved as a resumable session under ~/.claude.
BROWSER_CLAUDE_ARGS = ["--tools", "", "--strict-mcp-config", "--no-session-persistence"]


@app.post("/browser/v1/chat/completions")
async def browser_chat_completions(request: Request):
    """Brave Leo's "Bring your own model" (or any browser assistant), with no tools.

    No ``bridge`` object and no session: Claude runs in plan mode in the configured workdir,
    answers from the messages alone, and an error comes back as reply text Leo can show.
    """
    body = await _json_object(request)
    if isinstance(body, JSONResponse):
        return body
    if body.get("bridge") is not None:
        return JSONResponse(
            _error_json("/browser takes no bridge object; use /v1/chat/completions", "bad_request"),
            status_code=400,
        )
    model = str(body.get("model") or "")
    route = parse_cli_model(model)
    if route is None or route[0].flavor not in BROWSER_FLAVORS:
        return JSONResponse(
            _error_json(
                f"/browser runs Claude only (claude:<model>), not {model!r}: it is the one CLI "
                "whose every tool the bridge can turn off",
                "browser_model_unsupported",
            ),
            status_code=400,
        )
    spec, sub_model = route
    if (refusal := _bad_model_id(sub_model)) is not None:
        return refusal
    system_text, prompt = render_transcript(body.get("messages"))
    if not prompt:
        return _no_user_message()
    events = run_agent(
        spec.command,
        prompt=prompt,
        system_text=system_text,
        model=sub_model,
        permission_mode="plan",
        cwd=_workdir(),
        allowed_tools=[],
        cli_args=list(BROWSER_CLAUDE_ARGS),
        web_scout=False,
        security_log=SecurityLog(source="gateway-browser"),
    )
    return await _turn_response(
        model, events, request=request, stream=bool(body.get("stream")), command=spec.command,
        token="", session_id=None, is_error_text=True,
    )


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", DEFAULT_PORT))
    # Create both tokens now, so apps and the web UI find them before the first request.
    gateway_auth.client_token()
    gateway_auth.owner_token()
    folder = gateway_auth.bridge_home()
    print(
        f"Bearer tokens: apps: {folder / gateway_auth.TOKEN_FILE}, "
        f"owner and web UI: {folder / gateway_auth.OWNER_TOKEN_FILE} "
        f"(or ${gateway_auth.TOKEN_ENV} / ${gateway_auth.OWNER_TOKEN_ENV})",
        flush=True,
    )
    # Loopback only, by design (see compliance stance).
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
