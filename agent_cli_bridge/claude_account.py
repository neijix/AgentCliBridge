"""Which account this machine's Claude Code runs on: the owner's own, or the company's.

Read from files and the environment only (no ``claude auth status`` spawn), so it is cheap enough
for every hello and agents update:

- **work** — Claude Code talks to something other than Anthropic's API: ``ANTHROPIC_BASE_URL``
  on another host (a company AI gateway, e.g. ``127.0.0.1:4000``), Bedrock / Vertex / Foundry,
  or a claude.ai Team / Enterprise organization. The process environment and the ``env`` of
  ``~/.claude/settings.json`` both count, as they do for Claude Code itself.
- **personal** — signed in to claude.ai (Google or e-mail) on a Pro / Max / free organization.
- ``None`` — neither can be told (no sign-in yet, a bare API key): the list shows no tag.

``claude_gateway`` names that company gateway itself: ``model_catalog`` reads its model list.

A machine can hold one Claude Code profile per code root:
``~/.claude-profiles`` lists ``<root>\t<config dir>`` lines, and a session started inside a root
runs with ``CLAUDE_CONFIG_DIR`` set to its dir (``claude_profile_env``). A directory this process
merely inherited does not pin every project to that one login, and a machine-wide company
gateway stays on the work profile. A directory this spawn set itself (a D3SKHAND account) wins.
Every read here follows ``CLAUDE_CONFIG_DIR`` as Claude Code does: its ``settings.json`` and
``.claude.json`` live there.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_CLOUD_SWITCHES = {
    "CLAUDE_CODE_USE_BEDROCK": "Bedrock",
    "CLAUDE_CODE_USE_VERTEX": "Vertex",
    "CLAUDE_CODE_USE_FOUNDRY": "Foundry",
}
# This computer's route to Claude — a company gateway, a cloud, its key or token, its model
# names. A profile that does not set one itself must not inherit it from the process: a personal
# login sent through the office gateway fails ("Unexpected value(s) `prompt-caching-scope-…`").
# Claude Code reads a blank value as unset. D3SKHAND's account turns blank the same names.
CLAUDE_ROUTE_VARIABLES = (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_BETAS",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_VERTEX_PROJECT_ID",
    "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
)
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


def _profile_lines(home: Path) -> list[tuple[str, str]]:
    """``(code root, config dir)`` from ``~/.claude-profiles``; none when the record is missing."""
    try:
        lines = (home / PROFILES_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    found = []
    for line in lines:
        root, _, config_dir = line.partition("\t")
        root, config_dir = root.strip(), config_dir.strip()
        if root and config_dir:
            found.append((root, config_dir))
    return found


def claude_profile_dir(home: Path, cwd: str | os.PathLike[str]) -> str | None:
    """The config dir of the profile whose code root holds ``cwd`` (``~/.claude-profiles``), or ``None``."""
    try:
        here = _comparable(str(Path(cwd).resolve())) + "/"
    except (OSError, RuntimeError):
        return None
    for root, config_dir in _profile_lines(home):
        if here.startswith(_comparable(root) + "/"):
            return config_dir
    return None


def _caller_chose_login(env: Mapping[str, str], inherited: Mapping[str, str]) -> bool:
    """Whether this spawn named its own Claude login, rather than merely inheriting the process's.

    A D3SKHAND account sets ``CLAUDE_CONFIG_DIR`` to its own folder and blanks the machine's
    route. That choice wins over the code-root profile. The directory the node process inherited
    — whichever folder happened to start it — does not.
    """
    configured = env.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured and configured != inherited.get("CLAUDE_CONFIG_DIR", "").strip():
        return True
    return any(name in env and env.get(name, "") != inherited.get(name, "") for name in CLAUDE_ROUTE_VARIABLES)


def _login_kind(home: Path, config_dir: str) -> str:
    """``work`` / ``personal`` / ``""`` from that dir's own files, not from a machine-wide gateway."""
    probe = {"CLAUDE_CONFIG_DIR": config_dir} if config_dir else {}
    found = claude_account(home, probe)
    return str(found["kind"]) if found else ""


def _keeps_machine_route(home: Path, config_dir: str) -> bool:
    """Whether a session on that login keeps the machine's own route to Claude.

    A work login does. So does a code root's profile with no sign-in of its own: it can only
    reach Claude through the gateway the user's environment names (an office profile that relies
    on the machine-wide ``ANTHROPIC_BASE_URL`` / ``ANTHROPIC_AUTH_TOKEN``); blanking them there
    leaves Claude Code "Not logged in". A personal sign-in, and the default directory outside
    every root unless it is work, do not.
    """
    kind = _login_kind(home, config_dir)
    return kind == "work" or (bool(config_dir) and not kind)


def claude_profile_env(
    env: Mapping[str, str], cwd: str | os.PathLike[str] | None, home: Path | None = None,
    inherited: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """``env`` for a Claude Code session started in ``cwd``.

    The profile of the code root that holds ``cwd`` (``claude_profile_dir``; ``cwd`` ``None`` =
    this process's directory). A login this spawn set itself wins (``_caller_chose_login``).
    Otherwise a ``CLAUDE_CONFIG_DIR`` this process inherited is replaced by the profile, or
    removed outside every root so Claude uses its default directory. On a login that does not
    keep the machine's route (``_keeps_machine_route``), route variables that login's own settings
    do not set are blanked — Claude Code reads a blank as unset — so the office gateway does not
    ride along onto the personal login.
    No profile record: ``env`` comes back unchanged.
    """
    result = dict(env)
    own = home or Path.home()
    if _caller_chose_login(result, os.environ if inherited is None else inherited):
        return result
    if not _profile_lines(own):
        return result
    config_dir = claude_profile_dir(own, cwd if cwd is not None else os.getcwd()) or ""
    if config_dir:
        result["CLAUDE_CONFIG_DIR"] = config_dir
    else:
        # Removed, not blanked: Claude Code takes an empty CLAUDE_CONFIG_DIR as the current folder
        # and writes its config (projects/, backups/, plugins/) into the project.
        result.pop("CLAUDE_CONFIG_DIR", None)
    if not _keeps_machine_route(own, config_dir):
        settings = _settings_env(own, {"CLAUDE_CONFIG_DIR": config_dir} if config_dir else {})
        for name in CLAUDE_ROUTE_VARIABLES:
            if name not in settings and result.get(name, "").strip():
                result[name] = ""
    return result


def claude_profile_accounts(home: Path) -> dict[str, Any] | None:
    """Each code root's Claude login, read from its own files, or ``None`` when none are recorded.

    ``{"default": {kind, detail} | None, "roots": [{"root", "account"}]}``. ``default`` is the
    login outside every root (``~/.claude``). Kinds ignore a machine-wide gateway, so a personal
    root and a work root do not both come back as work.
    """
    lines = _profile_lines(home)
    if not lines:
        return None
    return {
        "default": claude_account(home, {}),
        "roots": [
            {"root": root, "account": claude_account(home, {"CLAUDE_CONFIG_DIR": config_dir})}
            for root, config_dir in lines
        ],
    }


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
