"""Who may call the gateway: this machine's own pages, holding a bearer token.

The gateway runs the owner's CLIs with the owner's logins, so every request must:

- name this machine in ``Host`` (``localhost``, ``127.0.0.1``, ``[::1]``, any port): a page
  on another site that rebinds its DNS name to 127.0.0.1 still sends its own name and is
  refused;
- come from no browser page, or from the gateway's own page (``Origin`` on this machine with the
  port of ``Host``): a page elsewhere, or on another local port, cannot reach the API, not even
  with a CORS-free "simple" request;
- carry ``Authorization: Bearer <token>``, except the two static pages (``/``, ``/security``),
  which hold no data and ask for the token themselves.

Two tokens, each from its env var, else its file under the bridge home
(``$AGENT_CLI_BRIDGE_HOME``, or ``~/.agent-cli-bridge``), created on first use mode 0600 and
readable by the owner only:

- **client** (``BRIDGE_TOKEN``, ``gateway-token``): what an app uses to chat.
- **owner** (``BRIDGE_OWNER_TOKEN``, ``gateway-owner-token``): everything a client may, plus what
  can escape a turn's limits — a write-capable permission mode, a ``bridge.cwd`` outside the
  configured workdir, ``bridge.env``, ``bridge.cli_args``, changing the gateway's config, clearing
  the security log. The web UI uses it.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from .argv import permission_args

log = logging.getLogger(__name__)

CallerRole = Literal["owner", "client"]

LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
HOME_ENV = "AGENT_CLI_BRIDGE_HOME"
TOKEN_ENV = "BRIDGE_TOKEN"
OWNER_TOKEN_ENV = "BRIDGE_OWNER_TOKEN"
TOKEN_FILE = "gateway-token"
OWNER_TOKEN_FILE = "gateway-owner-token"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def bridge_home_path(env: Mapping[str, str] | None = None) -> Path:
    """The bridge home path, without creating it.

    ``$AGENT_CLI_BRIDGE_HOME`` when that mapping sets it, else ``~/.agent-cli-bridge``.
    """
    values = os.environ if env is None else env
    explicit = values.get(HOME_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".agent-cli-bridge"


def bridge_home() -> Path:
    """The bridge home, created mode 0700 so a private log and token cannot leak beside it."""
    path = bridge_home_path()
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path, 0o700)  # mkdir's mode is masked; an existing directory keeps its old mode
    return path


def default_workdir() -> Path:
    """The directory the CLIs run in when nothing configures one: a sibling of the bridge home.

    Never inside the bridge home: its token files would sit next to the CLI's working directory.
    ``~/.agent-cli-bridge`` gives ``~/.agent-cli-bridge-work``. Not created here.
    """
    home = bridge_home_path()
    return home.with_name(f"{home.name}-work")


def write_private(path: Path, text: str, *, exclusive: bool = False) -> None:
    """Create or replace ``path`` mode 0600. A symlink is refused, not followed."""
    _refuse_symlink(path)
    flags = os.O_WRONLY | os.O_CREAT | _NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)  # O_TRUNC on an existing file does not change its mode
        _write_all(fd, text.encode())
    finally:
        os.close(fd)


def append_private(path: Path, text: str) -> None:
    """Append ``text`` to ``path``, creating it mode 0600. A symlink is refused, not followed."""
    _refuse_symlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _NOFOLLOW, 0o600)
    try:
        if sys.platform != "win32":
            os.fchmod(fd, 0o600)
        _write_all(fd, text.encode())
    finally:
        os.close(fd)


def _refuse_symlink(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing to follow the symlink {path}")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _is_owner_private(info: os.stat_result) -> bool:
    """True when this user owns ``info`` and, on POSIX, group and other have no bits.

    Windows has no POSIX group/other bits; those are not a reason to reject a token there.
    """
    getuid = getattr(os, "getuid", None)
    if getuid is not None and info.st_uid != getuid():
        return False
    if sys.platform == "win32":
        return True
    return stat.S_IMODE(info.st_mode) & 0o077 == 0


def is_local_origin(origin: str | None, host: str | None) -> bool:
    """True when no page sent the request, or the gateway's own page (same origin as ``host``) did.

    The pages the gateway serves (``/``, ``/security``) are the only browser callers: Brave Leo
    posts from the browser process with no ``Origin``, and the apps call through ``run_agent``.
    A page on another local port or another loopback name (a dev server on ``[::1]:4747`` while
    the gateway is on ``127.0.0.1:4747``) is refused: the gateway's own page fetches relative
    paths, so its ``Origin`` always names the ``Host`` it was loaded from.
    """
    if not origin:
        return True  # no Origin header: same-origin GET, curl, an app's HTTP client
    try:
        parts = urlsplit(origin)
        origin_port = parts.port or 80
        host_parts = urlsplit(f"//{host or ''}")
        host_port = host_parts.port or 80
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and parts.hostname in LOCAL_HOSTNAMES
        and parts.hostname == host_parts.hostname
        and origin_port == host_port
    )


def is_local_host(host: str | None) -> bool:
    """True when the ``Host`` header names this machine (DNS-rebinding guard)."""
    if not host or any(c in host for c in "@/?#\\ \t"):
        return False  # a Host header is name[:port], never userinfo, a path or spaces
    try:
        parts = urlsplit(f"//{host}")
        hostname = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    return hostname in LOCAL_HOSTNAMES


def load_token(env_key: str, filename: str, directory: Path | None = None) -> str:
    """The token in ``$env_key``, else in ``directory/filename``, created there when missing."""
    from_env = os.environ.get(env_key, "").strip()
    if from_env:
        return from_env
    path = (directory or bridge_home()) / filename
    existing = _read_token(path)
    if existing:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        write_private(path, token + "\n", exclusive=True)
    except FileExistsError:
        # Another process is creating it: use theirs once written. Still empty (a truncated
        # file): replace it, or every request would fail on a token nobody can present.
        # Replacing also sets 0600; truncating alone would keep a looser mode.
        for _ in range(20):
            existing = _read_token(path)
            if existing:
                return existing
            time.sleep(0.05)
        write_private(path, token + "\n")
    log.info("created the gateway token file %s", path)
    return token


def _read_token(path: Path) -> str:
    """The token text, or "" when the file is missing or empty.

    A symlink is not followed. A non-empty file is rejected unless this user owns it and, on
    POSIX, no group or other permission bit is set — an empty file is left for the caller to
    refill mode 0600.
    """
    _refuse_symlink(path)
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise OSError(f"refusing to read the token file {path}") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        text = handle.read().strip()
    if text and not _is_owner_private(info):
        raise OSError(f"refusing token file {path} that is not private to this user")
    return text


def client_token(directory: Path | None = None) -> str:
    return load_token(TOKEN_ENV, TOKEN_FILE, directory)


def owner_token(directory: Path | None = None) -> str:
    return load_token(OWNER_TOKEN_ENV, OWNER_TOKEN_FILE, directory)


def bearer_token(authorization: str | None) -> str:
    """The token of an ``Authorization: Bearer <token>`` header, else ``""``."""
    scheme, _, token = (authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def caller_role(authorization: str | None, directory: Path | None = None) -> CallerRole | None:
    """``"owner"``, ``"client"``, or None when the header carries neither token.

    Reads the tokens on every call (two tiny files on loopback): a replaced token file takes
    effect without restarting the gateway.
    """
    presented = bearer_token(authorization)
    if not presented:
        return None
    if _same(presented, owner_token(directory)):
        return "owner"
    if _same(presented, client_token(directory)):
        return "client"
    return None


def _same(presented: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(presented.encode(), expected.encode())


# Modes whose argv is not that flavor's bypass, but a client token still may not set (the write
# modes, and Claude's ``manual``, whose default tool list holds Bash on a non-live turn).
# Cursor, Gemini, and Copilot have no row: their write modes already share the bypass argv
# (Cursor ``--force``, Gemini yolo, Copilot ``--allow-all-tools``, including Copilot ``manual``).
# Antigravity's write modes stay client-allowed; only its bypass is owner-only, via argv.
_EXTRA_OWNER_ONLY_MODES: dict[str, frozenset[str]] = {
    "claude": frozenset({"acceptEdits", "auto", "dontAsk", "manual"}),
    "grok": frozenset({"auto"}),
    "opencode": frozenset({"acceptEdits", "auto", "dontAsk"}),
}


def _argv_matches_bypass(flavor: str, mode: str) -> bool:
    """True for ``bypassPermissions``, or any mode this flavor runs with the same flags."""
    return (
        mode == "bypassPermissions"
        or permission_args(flavor, mode) == permission_args(flavor, "bypassPermissions")
    )


def _real_path(path: str) -> Path:
    """Absolute path from the process's current directory, symlinks resolved."""
    return Path(path).resolve()


def _cwd_is_owner_only(cwd: str, workdir: str | None) -> bool:
    """True unless ``cwd`` realpaths to ``workdir`` or a directory under it.

    ``workdir`` None — neither ``BRIDGE_WORKDIR`` nor a runtime override — refuses every cwd.
    """
    if workdir is None or not workdir.strip():
        return True
    root = _real_path(workdir)
    target = _real_path(cwd)
    return target != root and root not in target.parents


def owner_only_options(opts: Mapping[str, Any], flavor: str, *, workdir: str | None) -> list[str]:
    """Bridge options only the owner token may send to a ``flavor`` CLI.

    The route consults this and does not decide for itself. ``permission_mode`` is listed when
    it is bypass, when this flavor's argv for it equals bypass, or when ``_EXTRA_OWNER_ONLY_MODES``
    names it. ``cwd`` is listed unless its real path is ``workdir`` or a descendant; a symlink
    that leaves ``workdir`` is listed. ``env`` and ``cli_args``, when non-empty, are always listed.
    """
    found: list[str] = []
    mode = opts.get("permission_mode")
    if mode:
        text = str(mode)
        if _argv_matches_bypass(flavor, text):
            found.append(f"bridge.permission_mode={text} (approves every {flavor} tool)")
        elif text in _EXTRA_OWNER_ONLY_MODES.get(flavor, ()):
            found.append(f"bridge.permission_mode={text} (write mode for {flavor})")
    cwd = opts.get("cwd")
    if cwd and _cwd_is_owner_only(str(cwd), workdir):
        found.append("bridge.cwd")
    if opts.get("env"):
        found.append("bridge.env")
    if opts.get("cli_args"):
        found.append("bridge.cli_args")
    return found
