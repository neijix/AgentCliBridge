"""Which account this machine's Claude Code runs on: the owner's own, or the company's.

Read from files and the environment only (no ``claude auth status`` spawn), so it is cheap enough
for every hello and agents update:

- **work** — Claude Code talks to something other than Anthropic's API: ``ANTHROPIC_BASE_URL``
  on another host (a company AI gateway, e.g. ``127.0.0.1:4000``), Bedrock / Vertex / Foundry,
  or a claude.ai Team / Enterprise organization. The process environment and the ``env`` of
  ``~/.claude/settings.json`` both count, as they do for Claude Code itself.
- **personal** — signed in to claude.ai (Google or e-mail) on a Pro / Max / free organization.
- ``None`` — neither can be told (no sign-in yet, a bare API key): the list shows no tag.

``claude_gateway`` names that company gateway itself, ``claude_gateway_headers`` the credentials
Claude Code sends it: ``model_catalog`` reads its model list with them.

A machine can hold one Claude Code profile per code root:
``~/.claude-profiles`` lists ``<root>\t<config dir>`` lines, and a session started inside a root
runs with ``CLAUDE_CONFIG_DIR`` set to its dir (``claude_profile_env``). Every read here follows
``CLAUDE_CONFIG_DIR`` as Claude Code does: its ``settings.json`` and ``.claude.json`` live there.
"""

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_CLOUD_SWITCHES = {
    "CLAUDE_CODE_USE_BEDROCK": "Bedrock",
    "CLAUDE_CODE_USE_VERTEX": "Vertex",
    "CLAUDE_CODE_USE_FOUNDRY": "Foundry",
}
_WORK_ORGANIZATIONS = {"claude_team", "claude_enterprise"}
_PLAN_NAMES = {"claude_max": "Max", "claude_pro": "Pro", "claude_free": "Free"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_on(value: str) -> bool:
    return value.strip().lower() not in ("", "0", "false", "no", "off")


PROFILES_FILE = ".claude-profiles"


def _config_dir(env: Mapping[str, str]) -> Path | None:
    """``CLAUDE_CONFIG_DIR`` when set, else ``None`` (Claude Code's default layout under the home)."""
    configured = env.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _settings_env(home: Path, env: Mapping[str, str]) -> dict[str, str]:
    config_dir = _config_dir(env) or home / ".claude"
    found = _read_json(config_dir / "settings.json").get("env")
    return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(found, dict) else {}


def _claude_env(home: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The environment Claude Code runs with: the process's, its settings' ``env`` on top."""
    return {**env, **_settings_env(home, env)}


def _comparable(path: str) -> str:
    """A path as the profile record writes it (forward slashes), case-folded where the OS is."""
    text = path.replace("\\", "/").rstrip("/")
    return text.lower() if os.name == "nt" else text


def claude_profile_dir(home: Path, cwd: str | os.PathLike[str]) -> str | None:
    """The config dir of the profile whose code root holds ``cwd`` (``~/.claude-profiles``), or ``None``."""
    try:
        lines = (home / PROFILES_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    try:
        here = _comparable(str(Path(cwd).resolve())) + "/"
    except (OSError, RuntimeError):
        return None
    for line in lines:
        root, _, config_dir = line.partition("\t")
        root, config_dir = root.strip(), config_dir.strip()
        if root and config_dir and here.startswith(_comparable(root) + "/"):
            return config_dir
    return None


def claude_profile_env(env: Mapping[str, str], cwd: str | os.PathLike[str] | None, home: Path | None = None) -> dict[str, str]:
    """``env`` with ``CLAUDE_CONFIG_DIR`` set for a Claude Code session started in ``cwd``.

    The profile of the code root that holds ``cwd`` (``claude_profile_dir``; ``cwd`` ``None`` =
    this process's directory). A ``CLAUDE_CONFIG_DIR`` already in ``env`` wins, as it does in
    the shell's ``claude`` function; outside every root ``env`` comes back unchanged.
    """
    result = dict(env)
    if result.get("CLAUDE_CONFIG_DIR", "").strip():
        return result
    config_dir = claude_profile_dir(home or Path.home(), cwd if cwd is not None else os.getcwd())
    if config_dir:
        result["CLAUDE_CONFIG_DIR"] = config_dir
    return result


def _cloud(merged: Mapping[str, str]) -> str:
    """Bedrock / Vertex / Foundry when one is switched on (Claude Code then ignores the base URL)."""
    return next((cloud for switch, cloud in _CLOUD_SWITCHES.items() if _is_on(merged.get(switch, ""))), "")


def _gateway_host(base_url: str) -> str:
    """``host`` or ``host:port`` of a base URL that is not Anthropic's own API, else ``""``."""
    parts = urlsplit(base_url.strip())
    try:
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:  # a port that is not a number: Claude Code cannot reach it either
        return ""
    if not host or host == "anthropic.com" or host.endswith(".anthropic.com"):
        return ""
    return f"{host}:{port}" if port else host


def claude_gateway(home: Path, env: Mapping[str, str]) -> str | None:
    """The company gateway this machine's Claude Code talks to (its ``ANTHROPIC_BASE_URL``), or ``None``.

    ``None`` for Anthropic's own API, a URL that is not http(s), and Bedrock / Vertex / Foundry.
    """
    merged = _claude_env(home, env)
    base_url = merged.get("ANTHROPIC_BASE_URL", "").strip()
    if _cloud(merged) or urlsplit(base_url).scheme.lower() not in ("http", "https"):
        return None
    return base_url if _gateway_host(base_url) else None


_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$")


def claude_gateway_headers(home: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The headers Claude Code sends its company gateway, or ``{}`` when it talks to none.

    ``ANTHROPIC_CUSTOM_HEADERS`` (``Name: value`` lines), then ``ANTHROPIC_API_KEY`` as
    ``x-api-key`` and ``ANTHROPIC_AUTH_TOKEN`` as a bearer — what Claude Code itself sends that
    same URL, so a gateway that lists its models only to a signed-in caller can be read.
    An ``apiKeyHelper`` script is not run.
    """
    if claude_gateway(home, env) is None:
        return {}
    merged = _claude_env(home, env)
    headers: dict[str, str] = {}
    for line in merged.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines():
        name, colon, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if colon and _HEADER_NAME.match(name) and value and value.isprintable():
            headers[name] = value
    api_key = merged.get("ANTHROPIC_API_KEY", "").strip()
    token = merged.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if api_key.isprintable() and api_key:
        headers["x-api-key"] = api_key
    if token.isprintable() and token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def claude_account(home: Path, env: Mapping[str, str]) -> dict[str, str] | None:
    """``{"kind": "work" | "personal", "detail": <gateway host, cloud or plan>}``, or ``None``."""
    merged = _claude_env(home, env)
    cloud = _cloud(merged)
    if cloud:
        return {"kind": "work", "detail": cloud}
    host = _gateway_host(merged.get("ANTHROPIC_BASE_URL", ""))
    if host:
        return {"kind": "work", "detail": host}
    config_dir = _config_dir(env)
    account = _read_json((config_dir or home) / ".claude.json").get("oauthAccount")
    if not isinstance(account, dict) or not account.get("accountUuid"):
        return None
    organization = str(account.get("organizationType") or "")
    if organization in _WORK_ORGANIZATIONS:
        return {"kind": "work", "detail": organization.removeprefix("claude_").capitalize()}
    return {"kind": "personal", "detail": _PLAN_NAMES.get(organization, "claude.ai")}
