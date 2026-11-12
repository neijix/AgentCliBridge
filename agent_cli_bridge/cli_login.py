"""Sign an agent CLI in from a host's page (Settings › Agents, or the "not logged in" error)

Some CLIs sign in through a browser page that polls: ``cursor-agent login`` prints a
``cursor.com/loginDeepControl`` link and waits until someone approves it in any browser, then
stores the login on this machine. Claude Code's ``auth login --claudeai`` prints a
``claude.com/cai/oauth/authorize`` link and then waits for the owner to paste the code the
page shows (the browser cannot reach a callback on the host). Grok's ``login --device-auth``
prints an ``auth.x.ai`` link plus a short code to type on that page. Open Router
(``opencode auth login -p openrouter -m key``) has no browser round-trip: the page opens
``openrouter.ai/keys`` and the owner pastes the key into the host's page, which the waiting CLI
reads. Copilot CLI (``login --device-code``) prints ``github.com/login/device`` and a code to type
there; it has no status or logout command, so its sign-in is read from ``~/.copilot/config.json``
(or the GitHub CLI's login it falls back on) and signing out is left to its own ``/logout``. The host runs that command with the browser opening turned off, reads the link from
its output and hands it to its page; the owner opens it wherever they are, and the CLI —
still waiting on the host — finishes by itself. Nothing here ever logs a password, token or
key: the CLI keeps its own login, as when it is run in a terminal.

Only CLIs listed in ``LOGIN_SPECS`` can be signed in this way; the argv is built here from the
binary the host discovered, never taken from the request, and the link must be ``https`` on the
CLI's own host before the browser is ever told to open it. Antigravity and Gemini CLI have no
headless login command (TUI only), so they stay out.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from .processes import background_process_options


def _drop_download_quarantine(binary: str) -> None:
    """The sign-in command is an exec. A quarantined CLI would show Gatekeeper's trash dialog."""
    # Lazy import: cli_status imports this module at load time.
    from .cli_status import clear_macos_quarantine

    clear_macos_quarantine(binary)

LINK_WAIT = 20.0  # the link shows up within a second or two
LOGIN_TIMEOUT = 10 * 60.0  # the owner has that long to approve it in a browser
STATUS_TIMEOUT = 20.0
STOP_GRACE = 3.0  # a login told to stop has that long to exit before it is killed
CODE_MAX = 2048  # a pasted OAuth code, callback URL or API key, never a dump
_OUTPUT_TAIL = 4000
_URL_RE = re.compile(r"https://[^\s\"'<>]+")
# Bearer values and API-key shapes. A key does not have to start with ``sk-``.
_SECRET_RE = re.compile(
    "(?i)"
    r"\b(?:sk-[a-z0-9_-]{8,}|sk-or-v1-[a-z0-9]+|xai-[a-z0-9_-]{8,})\b"
    r"|\bbearer\s+[a-z0-9._~+/=-]{16,}"
    r"|\b(?:api[-_\s]?key|x-api-key)\s*[:=]\s*[\"']?[a-z0-9._~+/=-]{8,}"
    r"|\b(?:ghp|gho|ghu|ghs|ghr)_[a-z0-9]{16,}\b"
    r"|\bgithub_pat_[a-z0-9_]{22,}\b"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_USER_CODE_IN_TEXT = re.compile(
    r"(?:user[_ ]code|enter(?: the)? code|one-time code|shows this code)"
    # "code: ABCD" — or, with no separator (Copilot's "enter code 92EC-55BB"), only a dashed code.
    r"(?:\s*[:=]\s*([A-Z0-9]{4,8}(?:-[A-Z0-9]{4,8})?)|\s+([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\b)",
    re.I,
)
_COPILOT_TOKEN_ENV = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")


@dataclass(frozen=True)
class LoginSpec:
    login: tuple[str, ...]
    status: tuple[str, ...]
    logout: tuple[str, ...]
    env: dict[str, str]
    hosts: tuple[str, ...]  # a link on another host is never handed to the browser
    reads_code: bool = False  # stdin stays open so a pasted page code / key can finish the login
    needs_link: bool = True  # False: Open Router — a static keys page, no URL from the CLI
    page: str = ""  # https page on ``hosts`` used when the CLI prints none
    read_status: Callable[[], bool | None] | None = None  # instead of running ``status``
    logout_hint: str = ""  # set when the CLI has no logout command: what the owner runs instead


_CURSOR = LoginSpec(
    login=("login",),
    status=("status",),
    logout=("logout",),
    env={"NO_OPEN_BROWSER": "1"},
    hosts=("cursor.com", "www.cursor.com"),
)
_CLAUDE = LoginSpec(
    login=("auth", "login", "--claudeai"),
    status=("auth", "status"),
    logout=("auth", "logout"),
    env={"NO_OPEN_BROWSER": "1", "BROWSER": "true"},
    hosts=("claude.com", "www.claude.com", "claude.ai"),
    reads_code=True,
)
_GROK = LoginSpec(
    login=("login", "--device-auth"),
    status=("models",),
    logout=("logout",),
    env={"NO_OPEN_BROWSER": "1", "BROWSER": "true"},
    hosts=("auth.x.ai", "www.auth.x.ai", "grok.com", "www.grok.com"),
)
def _copilot_config_users(folder: str) -> bool | None:
    """``logged_in_users`` in Copilot's config (JSON under ``//`` comment lines); None if unreadable."""
    try:
        with open(os.path.join(folder, "config.json"), encoding="utf-8") as handle:
            text = "".join(line for line in handle if not line.lstrip().startswith("//"))
    except FileNotFoundError:
        return False  # never launched
    except OSError:
        return None
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return None
    users = data.get("logged_in_users") if isinstance(data, dict) else None
    return bool(isinstance(users, list) and users)


def _gh_is_signed_in(path: str | None, run: Callable[..., Any]) -> bool:
    """GitHub CLI signed in to github.com (``gh auth status``'s exit code): Copilot CLI falls back
    on its token. ``gh auth token`` would print the token, so it is never asked."""
    gh = shutil.which("gh", path=path)
    if not gh:
        return False
    try:
        done = run(
            [gh, "auth", "status", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT,
            stdin=subprocess.DEVNULL,
            **background_process_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def copilot_signed_in(
    home: str | None = None,
    env: Mapping[str, str] | None = None,
    run: Callable[..., Any] = subprocess.run,
) -> bool | None:
    """Copilot CLI has no status command. It is signed in by its own login (``logged_in_users``
    in ``~/.copilot/config.json``), a token in the environment, or the GitHub CLI's login."""
    values = os.environ if env is None else env
    if any(values.get(name) for name in _COPILOT_TOKEN_ENV):
        return True
    folder = values.get("COPILOT_HOME") or os.path.join(home or os.path.expanduser("~"), ".copilot")
    from_config = _copilot_config_users(folder)
    if from_config:
        return True
    return True if _gh_is_signed_in(values.get("PATH"), run) else from_config


_COPILOT = LoginSpec(
    login=("login", "--device-code"),
    status=(),
    logout=(),
    env={"NO_OPEN_BROWSER": "1", "BROWSER": "true"},
    hosts=("github.com",),
    read_status=copilot_signed_in,
    logout_hint="Copilot CLI has no sign-out command — run copilot on that computer and type /logout",
)
_OPENROUTER = LoginSpec(
    login=("auth", "login", "-p", "openrouter", "-m", "key"),
    status=("auth", "list"),
    logout=("auth", "logout", "openrouter"),
    env={"NO_OPEN_BROWSER": "1", "BROWSER": "true"},
    hosts=("openrouter.ai", "www.openrouter.ai"),
    reads_code=True,
    needs_link=False,
    page="https://openrouter.ai/keys",
)
LOGIN_SPECS: dict[str, LoginSpec] = {
    "agent": _CURSOR,
    "cursor-agent": _CURSOR,
    "claude": _CLAUDE,
    "grok": _GROK,
    "opencode": _OPENROUTER,
    "copilot": _COPILOT,
}


def can_sign_in(command: str) -> bool:
    return command in LOGIN_SPECS


def sign_in_needs_code(command: str) -> bool:
    """Claude's page and Open Router's keys page need a paste; Cursor, Grok and Copilot finish in the browser."""
    spec = LOGIN_SPECS.get(command)
    return bool(spec and spec.reads_code)


def login_link(text: str, hosts: tuple[str, ...]) -> str:
    """The first https link on one of ``hosts`` in the CLI's output, else ""."""
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;)")
        parsed = urlparse(url)
        if parsed.scheme == "https" and (parsed.hostname or "").lower() in hosts:
            return url
    return ""


def login_user_code(text: str) -> str:
    """The short device-code a page asks the owner to type, if the CLI printed one."""
    for match in _URL_RE.finditer(text or ""):
        parsed = urlparse(match.group(0).rstrip(".,;)"))
        values = parse_qs(parsed.query).get("user_code") or []
        if values and values[0].strip():
            return values[0].strip()
    found = _USER_CODE_IN_TEXT.search(text or "")
    return (found.group(1) or found.group(2)).upper() if found else ""


def parse_signed_in(code: int, output: str) -> bool | None:
    """``<cli> status`` → True / False, or None when the answer says neither."""
    text = _ANSI_RE.sub("", output or "")
    for chunk in (text.strip(), *(line.strip() for line in text.splitlines())):
        if not chunk.startswith("{"):
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "loggedIn" in data:
            value = data["loggedIn"]
            if isinstance(value, bool):
                return value
        break
    lowered = text.lower()
    if "not logged in" in lowered or "not authenticated" in lowered or "authentication required" in lowered:
        return False
    # OpenCode's `auth list` names OpenRouter even when empty — 0 credentials wins.
    if re.search(r"\b0 credentials\b", lowered) or "no credentials" in lowered:
        return False
    # A credential line names the provider and its kind alone (`●  OpenRouter api`): any other
    # mention of OpenRouter (an error, a prompt, a hint) says nothing about being signed in.
    if re.search(r"^\W*openrouter\s+(?:api|oauth|wellknown)\s*$", lowered, re.M):
        return True
    if code == 0 and ("logged in" in lowered or "signed in" in lowered):
        return True
    return None


def _tail(text: str) -> str:
    """Last bytes of CLI output, with bearer tokens and API keys stripped (never shown in the UI)."""
    return _SECRET_RE.sub("[redacted]", (text or "")[-_OUTPUT_TAIL:].strip())


def _reap(process: Any) -> None:
    """End a login process and collect it: terminate, wait a moment, kill, wait again (no zombie)."""
    process.terminate()
    try:
        process.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=STOP_GRACE)


@dataclass
class _Login:
    process: Any
    started_at: float
    output: list[str] = field(default_factory=list)
    url: str = ""
    user_code: str = ""
    link_seen: threading.Event = field(default_factory=threading.Event)

    @property
    def text(self) -> str:
        return "".join(self.output)

    def is_running(self) -> bool:
        return self.process.poll() is None


class CliLogins:
    """One sign-in at a time per CLI; its process is left waiting for the browser."""

    def __init__(
        self,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        run: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        link_wait: float = LINK_WAIT,
    ) -> None:
        self._popen = popen
        self._run = run
        self._clock = clock
        self._link_wait = link_wait
        self._logins: dict[str, _Login] = {}
        self._lock = threading.Lock()

    def start(self, command: str, binary: str) -> dict[str, Any]:
        """Start ``<cli> login`` (or reuse the one still waiting) and return its link."""
        spec = LOGIN_SPECS.get(command)
        if spec is None:
            raise ValueError(f"This app cannot sign {command!r} in — run its own login on that computer")
        if not binary:
            raise ValueError(f"No {command!r} binary on this machine")
        _drop_download_quarantine(binary)
        with self._lock:
            self._expire()
            login = self._logins.get(command)
            if login is None or not login.is_running():
                login = self._spawn(spec, binary)
                self._logins[command] = login
        login.link_seen.wait(self._link_wait if spec.needs_link else min(self._link_wait, 1.0))
        if not login.url and spec.page:
            login.url = login_link(spec.page, spec.hosts)
        if not login.user_code:
            login.user_code = login_user_code(login.text) or login_user_code(login.url)
        if not login.url and spec.needs_link:
            ended = not login.is_running()
            if not ended:
                self._stop(command)
            raise ValueError(
                f"{command} login printed no sign-in link" + (f": {_tail(login.text)}" if login.text.strip() else "")
            )
        return {
            "url": login.url,
            "running": login.is_running(),
            "output": _tail(login.text),
            "needs_code": spec.reads_code,
            "user_code": login.user_code,
        }

    def submit(self, command: str, code: str) -> dict[str, Any]:
        """Hand a pasted sign-in code or API key to the CLI still waiting on stdin."""
        spec = LOGIN_SPECS.get(command)
        if spec is None or not spec.reads_code:
            raise ValueError(f"{command} sign-in does not take a pasted code")
        pasted = code.strip()
        if not pasted or "\n" in pasted or "\r" in pasted or len(pasted) > CODE_MAX:
            raise ValueError("Paste the code from the sign-in page")
        with self._lock:
            self._expire()
            login = self._logins.get(command)
            stdin = login.process.stdin if login and login.is_running() else None
            if login is None or stdin is None:
                raise ValueError("No sign-in is waiting — start it first")
            try:
                stdin.write(pasted + "\n\n")
                stdin.flush()
            except OSError as exc:
                raise ValueError("The sign-in ended before the code could be sent") from exc
        return {"ok": True, "running": login.is_running(), "needs_code": True}

    def status(self, command: str, binary: str) -> dict[str, Any]:
        """Whether the CLI is signed in now, and whether a sign-in is still waiting."""
        spec = LOGIN_SPECS.get(command)
        if spec is None:
            raise ValueError(f"This app cannot sign {command!r} in")
        with self._lock:
            self._expire()
            login = self._logins.get(command)
        signed_in, error = self._signed_in(spec, binary)
        running = bool(login and login.is_running())
        if not signed_in and spec.read_status and login and not running and login.process.returncode == 0:
            signed_in = True  # the login just ended cleanly: trust it over a config not read back yet
        return {
            "signed_in": signed_in,
            "running": running,
            "url": login.url if login and running else "",
            "output": _tail(login.text) if login else "",
            "error": error,
            "needs_code": bool(spec.reads_code and running and not signed_in),
            "user_code": (login.user_code if login and running else ""),
        }

    def logout(self, command: str, binary: str) -> dict[str, Any]:
        """Run ``<cli> logout`` (a sign-in still waiting is ended first), then report the status."""
        spec = LOGIN_SPECS.get(command)
        if spec is None:
            raise ValueError(f"This app cannot sign {command!r} out — run its own logout on that computer")
        if spec.logout_hint:
            raise ValueError(spec.logout_hint)
        with self._lock:
            self._stop(command)
        _drop_download_quarantine(binary)
        try:
            done = self._run(
                [binary, *spec.logout],
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT,
                stdin=subprocess.DEVNULL,
                **background_process_options(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f"{command} logout failed: {exc or exc.__class__.__name__}") from exc
        output = _tail(f"{done.stdout or ''}\n{done.stderr or ''}")
        if done.returncode != 0:
            raise ValueError(f"{command} logout failed" + (f": {output}" if output else ""))
        return {**self.status(command, binary), "output": output}

    def _signed_in(self, spec: LoginSpec, binary: str) -> tuple[bool | None, str]:
        """``(signed_in, error)`` from the spec's own reader, else from ``<cli> status``."""
        if spec.read_status is not None:
            return spec.read_status(), ""
        _drop_download_quarantine(binary)
        try:
            done = self._run(
                [binary, *spec.status],
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT,
                stdin=subprocess.DEVNULL,
                **background_process_options(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, str(exc) or exc.__class__.__name__
        return parse_signed_in(done.returncode, f"{done.stdout or ''}\n{done.stderr or ''}"), ""

    def _spawn(self, spec: LoginSpec, binary: str) -> _Login:
        env = {**os.environ, **spec.env}
        process = self._popen(
            [binary, *spec.login],
            stdin=subprocess.PIPE if spec.reads_code else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            **background_process_options(),
        )
        login = _Login(process=process, started_at=self._clock())
        threading.Thread(target=self._read, args=(login, spec), daemon=True).start()
        return login

    @staticmethod
    def _read(login: _Login, spec: LoginSpec) -> None:
        try:
            for line in login.process.stdout:
                login.output.append(line)
                if not login.url:
                    login.url = login_link(line, spec.hosts)
                if not login.user_code:
                    login.user_code = login_user_code(line)
                if login.url:
                    login.link_seen.set()
        except (OSError, ValueError):
            pass
        finally:
            login.link_seen.set()  # ended without a link: stop waiting for one

    def _expire(self) -> None:
        """End every login the owner waited on too long, and forget the finished ones that old."""
        for command, login in list(self._logins.items()):
            if self._clock() - login.started_at <= LOGIN_TIMEOUT:
                continue
            self._stop(command)
            del self._logins[command]

    def _stop(self, command: str) -> None:
        login = self._logins.get(command)
        if login and login.is_running():
            _reap(login.process)
