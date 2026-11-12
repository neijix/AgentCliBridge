"""Is each agent CLI on this machine up to date, and update it (a chat foot, Settings › Agents)

The host runs ``<cli> --version`` for every agent it found and asks that CLI's release channel
for the newest version: the npm registry's ``latest`` dist-tag for the CLIs published there
(Claude Code, Gemini CLI, Copilot CLI, Grok CLI, OpenCode) and Cursor's install script, which
names the build it would download. Antigravity's ``agy`` has no query-only check (``agy update``
installs), so it reports its installed version alone.

Everything is cached: the installed version for ten minutes (a ``brew upgrade`` shows up soon
enough), the newest version for an hour, a failure for five minutes — so a page can ask on
every chat switch without spawning processes or hitting the network each time. Nothing here is
ever an exception for the caller: a CLI that cannot be run, or a registry that does not answer,
is a row with an empty version and its reason.

Updating (``update_plan`` / ``run_update``) upgrades the copy the host runs, the way it was
installed — Homebrew, npm, or the CLI's own updater — from an argv built here, never taken from
a request.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .cli_login import can_sign_in, sign_in_needs_code
from .cli_tools import first_executable, windows_places, windows_tool
from .http_get import get_bytes, open_limited, read_bounded
from .processes import background_process_options

VERSION_TIMEOUT = 20.0  # a Node-based CLI can take a couple of seconds to print its version
FETCH_TIMEOUT = 10.0
INSTALLED_TTL = 10 * 60.0
LATEST_TTL = 60 * 60.0
FAILURE_TTL = 5 * 60.0
_MAX_BYTES = 512 * 1024  # dist-tags are ~100 bytes and the Cursor script ~6 KB

NPM_REGISTRY = "https://registry.npmjs.org"
NPM_PACKAGES = {
    "claude": "@anthropic-ai/claude-code",
    "gemini": "@google/gemini-cli",
    "copilot": "@github/copilot",
    "grok": "@xai-official/grok",
    "opencode": "opencode-ai",
}
CURSOR_INSTALL_URL = "https://cursor.com/install"
# A CLI installed as a Homebrew formula can only be upgraded to what that formula ships, which
# often lags npm by a release or two (opencode 1.18.30 in Homebrew while npm has 1.18.32): its
# newest version is asked from Homebrew's own API, else Update would promise what `brew upgrade`
# cannot deliver.
HOMEBREW_FORMULA_API = "https://formulae.brew.sh/api/formula"
_FORMULA_RE = re.compile(r"^[a-z0-9][a-z0-9+._@-]*$")
CURSOR_COMMANDS = ("agent", "cursor-agent")

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)(-[0-9A-Za-z.]+)?")
_CURSOR_BUILD_RE = re.compile(r"downloads\.cursor\.com/lab/([0-9][0-9A-Za-z.-]*)/")


def parse_version(text: str) -> str:
    """The first version-looking token of a ``--version`` output.

    ``2.1.280 (Claude Code)`` → ``2.1.280``; ``GitHub Copilot CLI 1.0.87.`` → ``1.0.87``;
    ``2026.09.18-9a7762b`` (Cursor) keeps its build suffix.
    """
    match = _VERSION_RE.search(text or "")
    return (match.group(1) + (match.group(2) or "")) if match else ""


def version_key(version: str) -> tuple[int, ...]:
    """The dotted numeric part as a tuple — what "newer" compares (``2.1.9`` < ``2.1.10``)."""
    match = _VERSION_RE.match((version or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_outdated(installed: str, latest: str) -> bool | None:
    """``True`` when the newest release is newer; ``None`` when either side is unknown."""
    here, there = version_key(installed), version_key(latest)
    if not here or not there:
        return None
    return there > here


def homebrew_formula(resolved: str) -> str:
    """The Homebrew formula a binary belongs to (``…/Cellar/<formula>/<version>/…``), else ``""``."""
    parts = PurePosixPath(resolved).parts if resolved else ()
    if "Cellar" not in parts:
        return ""
    at = parts.index("Cellar")
    name = parts[at + 1] if at + 1 < len(parts) else ""
    return name if _FORMULA_RE.match(name) else ""


def latest_url(command: str, formula: str = "", *, is_claude_cask: bool = False) -> str:
    """Where this CLI's newest version is published, or ``""`` when there is no query-only source."""
    if is_claude_cask:
        return CLAUDE_RELEASE_LATEST_URL
    if formula:
        return f"{HOMEBREW_FORMULA_API}/{urllib.parse.quote(formula, safe='@+')}.json"
    package = NPM_PACKAGES.get(command)
    if package:
        return f"{NPM_REGISTRY}/-/package/{urllib.parse.quote(package, safe='@')}/dist-tags"
    if command in CURSOR_COMMANDS:
        return CURSOR_INSTALL_URL
    return ""


def latest_source(command: str, formula: str = "", *, is_claude_cask: bool = False) -> str:
    if is_claude_cask:
        return "anthropic"
    if formula:
        return "homebrew"
    if command in NPM_PACKAGES:
        return "npm"
    if command in CURSOR_COMMANDS:
        return "cursor"
    return ""


def parse_latest(command: str, body: bytes, formula: str = "", *, is_claude_cask: bool = False) -> str:
    """The newest version in what that CLI's source answered; ``""`` when it cannot be read."""
    if is_claude_cask:
        version = parse_version(body.decode("utf-8", "replace"))
        return version if _PLAIN_VERSION.match(version) else ""
    if formula:
        try:
            info = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ""
        versions = info.get("versions") if isinstance(info, dict) else None
        return parse_version(str(versions.get("stable") or "")) if isinstance(versions, dict) else ""
    if command in NPM_PACKAGES:
        try:
            tags = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ""
        return parse_version(str(tags.get("latest") or "")) if isinstance(tags, dict) else ""
    if command in CURSOR_COMMANDS:
        match = _CURSOR_BUILD_RE.search(body.decode("utf-8", "replace"))
        return parse_version(match.group(1)) if match else ""
    return ""


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason) if reason else (str(exc) or exc.__class__.__name__)


def run_version(command: str, timeout: float = VERSION_TIMEOUT, path: str = "") -> str:
    """``<command> --version`` as text (stdout then stderr); raises on a missing or stuck binary.

    ``path`` is the binary discovery already found: it is the one launched, never a second lookup.
    """
    binary = path or ((shutil.which(command) or command) if os.name == "nt" else command)
    # This probe is often the first launch after a cask upgrade. Homebrew has already stamped
    # com.apple.quarantine, and launching the binary then is the "Not Opened / Move to Trash" dialog.
    clear_macos_quarantine(path or shutil.which(command) or binary)
    completed = subprocess.run(  # noqa: S603 — the command is one the host already discovered
        [binary, "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
        **background_process_options(),
    )
    return f"{completed.stdout or ''}\n{completed.stderr or ''}"


USER_AGENT = "AgentCliBridge"


def fetch_text(url: str, timeout: float = FETCH_TIMEOUT) -> bytes:
    """GET a small document from one of the fixed release sources above; raises on failure."""
    return get_bytes(
        url,
        _MAX_BYTES,
        timeout=timeout,
        headers={"Accept": "application/json, text/plain;q=0.5", "User-Agent": USER_AGENT},
    )


class CliStatus:
    """Installed vs newest version of each agent CLI, cached per command."""

    def __init__(
        self,
        *,
        run: Callable[[str], str] | None = None,
        fetch: Callable[[str], bytes] = fetch_text,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._run = run
        self._fetch = fetch
        self._clock = clock
        self._installed: dict[str, tuple[dict[str, str], float]] = {}  # command → (row, expires_at)
        self._paths: dict[str, str] = {}  # command → the binary the last status() found
        self._latest: dict[tuple[str, str], tuple[dict[str, str], float]] = {}  # (command, url) → …

    @property
    def fetch(self) -> Callable[[str], bytes]:
        """The release-source reader these checks use (a test's fake, or ``fetch_text``)."""
        return self._fetch

    def forget(self, command: str) -> None:
        """Drop what is cached for ``command`` — after an update its version must be read again."""
        self._installed.pop(command, None)
        for key in [key for key in self._latest if key[0] == command]:
            self._latest.pop(key, None)

    def installed(self, command: str, *, force: bool = False, path: str = "") -> dict[str, str]:
        path = path or self._paths.get(command, "")
        cached = self._installed.get(command)
        if cached and not force and cached[1] > self._clock():
            return cached[0]
        try:
            version = parse_version(self._run(command) if self._run else run_version(command, path=path))
            row = {"version": version, "error": "" if version else "no version in the output"}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            row = {"version": "", "error": _reason(exc)}
        ttl = INSTALLED_TTL if row["version"] else FAILURE_TTL
        self._installed[command] = (row, self._clock() + ttl)
        return row

    def latest(
        self, command: str, *, force: bool = False, formula: str = "", is_claude_cask: bool = False
    ) -> dict[str, str]:
        url = latest_url(command, formula, is_claude_cask=is_claude_cask)
        if not url:
            return {"version": "", "source": "", "error": ""}
        cached = self._latest.get((command, url))
        if cached and not force and cached[1] > self._clock():
            return cached[0]
        source = latest_source(command, formula, is_claude_cask=is_claude_cask)
        try:
            version = parse_latest(command, self._fetch(url), formula, is_claude_cask=is_claude_cask)
            row = {"version": version, "source": source, "error": "" if version else "no version in the answer"}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            row = {"version": "", "source": source, "error": _reason(exc)}
        ttl = LATEST_TTL if row["version"] else FAILURE_TTL
        self._latest[(command, url)] = (row, self._clock() + ttl)
        return row

    def status(self, agents: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
        """One row per agent — ``{command, name, installed, latest, is_outdated, source, error}``."""
        rows = []
        for agent in agents:
            command = str(agent.get("command") or "")
            if not command:
                continue
            path = str(agent.get("path") or "")
            self._paths[command] = path
            installed = self.installed(command, force=force, path=path)
            resolved = os.path.realpath(path) if path and os.name != "nt" else ""
            formula = homebrew_formula(resolved)
            # A Claude cask can only reach the binary Anthropic serves for download (the update
            # switches to `claude-code@latest`, then installs that file): npm's `latest` is often
            # a few hours ahead of it, and comparing with npm offered an Update that cannot happen.
            is_claude_cask = command == "claude" and is_claude_cask_binary(resolved)
            latest = self.latest(command, force=force, formula=formula, is_claude_cask=is_claude_cask)
            rows.append(
                {
                    "command": command,
                    "name": str(agent.get("name") or command),
                    "installed": installed["version"],
                    "latest": latest["version"],
                    "is_outdated": is_outdated(installed["version"], latest["version"]),
                    "source": latest["source"],
                    "error": installed["error"] or latest["error"],
                    "can_sign_in": can_sign_in(command),
                    "needs_code": sign_in_needs_code(command),
                }
            )
        return {"checked_at": self._clock(), "agents": rows}


# ── updating a CLI (Settings › Agents) ──
# The host picks the update command from where the binary really lives, so it upgrades the copy
# it runs and never installs a second one beside it: a Homebrew cask or formula is upgraded with
# that Homebrew, an npm global with the npm next to it, anything else with the CLI's own updater.
# The page only names the command; the argv is always built here, never taken from the request.

UPDATE_TIMEOUT = 600.0  # `brew upgrade` refreshes its taps first; an npm install downloads
_OUTPUT_TAIL = 4000
_NPM_PACKAGE_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")  # never an option
# A Homebrew cask whose newest version is not the one the foot compares with: `claude-code`
# tracks Claude Code's *stable* channel (npm's `stable` dist-tag), so `brew upgrade` answers
# "already installed" while npm's `latest` — what `claude-code@latest` and the native installer
# follow — is ahead. Updating such a cask means switching to its `@latest` twin: fetch the twin
# first (an unreachable download leaves everything as it was), then uninstall + install. Both
# casks link the same `/opt/homebrew/bin/claude`, so nothing else on the machine changes.
CASK_LATEST_TWIN = {"claude-code": "claude-code@latest"}
# `claude-code@latest` still lags npm for hours: Homebrew bumps the formula after Anthropic
# publishes. `brew upgrade` then says "Not upgrading claude-code@latest, the latest version is
# already installed" (exit 0) while https://downloads.claude.ai/claude-code-releases/latest is
# already newer. The desk downloads that exact binary — the cask's own url — and replaces the
# cask file. On macOS it has to carry Anthropic's signature first.
CLAUDE_LATEST_CASK = "claude-code@latest"
CLAUDE_RELEASE_LATEST_URL = "https://downloads.claude.ai/claude-code-releases/latest"
CLAUDE_RELEASE_HOST = "downloads.claude.ai"
ANTHROPIC_SIGN_ID = "com.anthropic.claude-code"
ANTHROPIC_TEAM_ID = "Q6L2SF6YDW"
DOWNLOAD_NAME = ".claude.agent-cli-bridge-download"  # beside the cask file, renamed over it
QUARANTINE_ATTR = "com.apple.quarantine"
CLAUDE_RELEASE_MIN_BYTES = 20 * 1024 * 1024
CLAUDE_RELEASE_MAX_BYTES = 400 * 1024 * 1024
_PLAIN_VERSION = re.compile(r"^\d+(?:\.\d+)+$")
_RELEASE_OS = {"Darwin": "darwin", "Linux": "linux"}
_RELEASE_ARCH = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}
# CLIs that update themselves when they were not installed by Homebrew or npm.
SELF_UPDATE = {
    "claude": ["update"],
    "agent": ["update"],
    "cursor-agent": ["update"],
    "agy": ["update"],
    "grok": ["update"],
    "opencode": ["upgrade"],
}


def _npm_package_at(parts: tuple[str, ...], index: int) -> str:
    """The package folder right after ``node_modules`` (two segments for a scoped one)."""
    if index + 1 >= len(parts):
        return ""
    name = parts[index + 1]
    if name.startswith("@") and index + 2 < len(parts):
        name = f"{name}/{parts[index + 2]}"
    return name if _NPM_PACKAGE_RE.match(name) else ""


def update_plan(
    command: str, binary: str, resolved: str, *, is_windows: bool = False, tool: Callable[[str], str] = windows_tool
) -> dict[str, Any]:
    """How to update ``command``: ``{argv, then, how}``, or ``{argv: [], hint}`` when the host cannot.

    ``binary`` is the path the host runs (``which``), ``resolved`` that path with symlinks
    followed — the Cellar / Caskroom / node_modules folder it points into says who installed it.
    ``then`` lists the commands to run after ``argv`` succeeded (a cask channel switch is three
    commands); it is empty for a plain upgrade. ``tool`` names a Windows helper's full path.
    """
    path_type = PureWindowsPath if is_windows else PurePosixPath
    parts = path_type(resolved).parts if resolved else ()
    if "Caskroom" in parts:
        at = parts.index("Caskroom")
        if at + 1 < len(parts):
            brew = str(path_type(*parts[:at]) / "bin" / "brew")
            token = parts[at + 1]
            twin = CASK_LATEST_TWIN.get(token)
            if twin:
                return {
                    "argv": [brew, "fetch", "--cask", twin],
                    "then": [[brew, "uninstall", "--cask", token], [brew, "install", "--cask", twin]],
                    "how": f"Homebrew — the {token} cask tracks the stable channel; switching to {twin}",
                }
            return {"argv": [brew, "upgrade", "--cask", token], "then": [], "how": "Homebrew"}
    if "Cellar" in parts:
        at = parts.index("Cellar")
        if at + 1 < len(parts):
            brew = str(path_type(*parts[:at]) / "bin" / "brew")
            return {"argv": [brew, "upgrade", parts[at + 1]], "then": [], "how": "Homebrew"}
    if "node_modules" in parts:
        at = parts.index("node_modules")
        package = _npm_package_at(parts, at)
        if package and at >= 1 and parts[at - 1] == "lib":
            npm = path_type(*parts[: at - 1]) / "bin" / "npm"
            return {"argv": [str(npm), "install", "-g", f"{package}@latest"], "then": [], "how": "npm"}
    if is_windows and command == "copilot":
        # WinGet's portable package lives here; Links/copilot.exe resolves into this folder.
        lowered = tuple(part.lower() for part in parts)
        if any(
            lowered[index : index + 2] == ("winget", "packages") and lowered[index + 2].startswith("github.copilot_")
            for index in range(len(lowered) - 2)
        ):
            return {
                "argv": [
                    tool("winget"), "upgrade", "--id", "GitHub.Copilot", "--exact", "--source", "winget",
                    "--silent", "--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements",
                ],
                "then": [],
                "how": "WinGet",
            }
    package = NPM_PACKAGES.get(command, "")
    if is_windows and package and binary.lower().endswith((".cmd", ".ps1")):
        # Shims live in the global prefix, but npm.cmd usually lives beside node.exe.
        # Pin the destination so another npm on PATH cannot update a different installation.
        prefix = path_type(binary).parent
        return {
            "argv": [tool("npm.cmd"), "install", "-g", "--prefix", str(prefix), f"{package}@latest"],
            "then": [],
            "how": "npm",
        }
    if command in SELF_UPDATE and binary:
        return {"argv": [binary, *SELF_UPDATE[command]], "then": [], "how": "its own updater"}
    hint = f"npm install -g {package}@latest" if package else ""
    return {"argv": [], "hint": hint or "update it the way it was installed"}


# ── uninstalling a CLI (Settings › Agents) ──
# The same reading of where the binary lives as an update: the Homebrew, npm or WinGet that
# installed it removes it. A CLI that installed itself (Claude's and Cursor's native installers)
# lives in one folder under ~/.local/share with symlinks in ~/.local/bin: those links and that
# folder are what removing it means. Grok's installer (install.sh / install.ps1) puts its binaries
# in ~/.grok/bin, beside its config and sign-in in ~/.grok: only that bin folder goes. Anything
# else is a hint — never a guess at what to delete.
NATIVE_INSTALL_DIRS = {"claude": "claude", "agent": "cursor-agent", "cursor-agent": "cursor-agent"}
OWN_BIN_DIRS = {"grok": (".grok", "bin")}
# WinGet keeps a portable package in WinGet\Packages\<Id>_<source>; the CLI resolves into it.
WINGET_PACKAGES = {"copilot": "GitHub.Copilot", "agy": "Google.AntigravityCLI"}


def _own_bin_install(command: str, resolved: str, home: Path) -> dict[str, Any]:
    """``{dir, links}`` for a CLI whose installer owns a whole ``bin`` folder, or ``{}``."""
    sub = OWN_BIN_DIRS.get(command)
    if not sub or not resolved:
        return {}
    bin_dir = home.joinpath(*sub)
    try:
        Path(resolved).relative_to(bin_dir)
    except ValueError:
        return {}
    if bin_dir.is_symlink() or not bin_dir.is_dir():
        return {}
    return {"dir": str(bin_dir), "links": []}


def _winget_package(command: str, parts: tuple[str, ...]) -> str:
    """The WinGet id ``command`` was installed from when ``parts`` lies in that package's folder."""
    package = WINGET_PACKAGES.get(command, "")
    if not package:
        return ""
    prefix = f"{package.lower()}_"
    lowered = tuple(part.lower() for part in parts)
    for index in range(len(lowered) - 2):
        if lowered[index : index + 2] == ("winget", "packages") and lowered[index + 2].startswith(prefix):
            return package
    return ""


def _native_install(command: str, binary: str, resolved: str, home: Path) -> dict[str, Any]:
    """``{dir, links}`` of a self-installed CLI under ``home``, or ``{}`` when it is not one."""
    folder = NATIVE_INSTALL_DIRS.get(command)
    if not folder or not binary or not resolved:
        return {}
    share = home / ".local" / "share" / folder
    bin_dir = home / ".local" / "bin"
    try:
        Path(resolved).relative_to(share)
    except ValueError:
        return {}
    if Path(binary).parent != bin_dir or share.is_symlink() or not share.is_dir():
        return {}
    links = []
    names = {"claude"} if folder == "claude" else {"agent", "cursor-agent"}
    for name in sorted(names):
        link = bin_dir / name
        if not link.is_symlink():
            continue
        try:
            Path(os.path.realpath(link)).relative_to(share)
        except ValueError:
            continue  # another CLI's link with the same name: never removed
        links.append(str(link))
    return {"dir": str(share), "links": links}


def uninstall_plan(
    command: str,
    binary: str,
    resolved: str,
    *,
    is_windows: bool = False,
    home: Path | None = None,
    tool: Callable[[str], str] = windows_tool,
) -> dict[str, Any]:
    """How to remove ``command``: ``{argv, how}``, ``{remove: {dir, links}, how}`` for a native
    install, or ``{argv: [], hint}`` when the host cannot remove it itself."""
    path_type = PureWindowsPath if is_windows else PurePosixPath
    parts = path_type(resolved).parts if resolved else ()
    if "Caskroom" in parts:
        at = parts.index("Caskroom")
        if at + 1 < len(parts):
            brew = str(path_type(*parts[:at]) / "bin" / "brew")
            return {"argv": [brew, "uninstall", "--cask", parts[at + 1]], "how": "Homebrew"}
    if "Cellar" in parts:
        at = parts.index("Cellar")
        if at + 1 < len(parts):
            brew = str(path_type(*parts[:at]) / "bin" / "brew")
            return {"argv": [brew, "uninstall", parts[at + 1]], "how": "Homebrew"}
    if "node_modules" in parts:
        at = parts.index("node_modules")
        package = _npm_package_at(parts, at)
        if package and at >= 1 and parts[at - 1] == "lib":
            npm = str(path_type(*parts[: at - 1]) / "bin" / "npm")
            return {"argv": [npm, "uninstall", "-g", package], "how": "npm"}
    winget = _winget_package(command, parts) if is_windows else ""
    if winget:
        return {
            "argv": [
                tool("winget"), "uninstall", "--id", winget, "--exact", "--source", "winget",
                "--silent", "--disable-interactivity", "--accept-source-agreements",
            ],
            "how": "WinGet",
        }
    package = NPM_PACKAGES.get(command, "")
    if is_windows and package and binary.lower().endswith((".cmd", ".ps1")):
        prefix = path_type(binary).parent
        return {"argv": [tool("npm.cmd"), "uninstall", "-g", "--prefix", str(prefix), package], "how": "npm"}
    native = _own_bin_install(command, resolved, home or Path.home())
    if not native and not is_windows:
        native = _native_install(command, binary, resolved, home or Path.home())
    if native:
        return {"argv": [], "remove": native, "how": "its own install folder"}
    where = f" ({binary})" if binary else ""
    return {"argv": [], "hint": f"remove it the way it was installed{where}"}


def remove_native_install(remove: dict[str, Any]) -> tuple[int, str]:
    """Delete what ``uninstall_plan`` named for a native install: its links, then its folder."""
    lines: list[str] = []
    try:
        for link in remove.get("links") or []:
            if os.path.islink(link):
                os.unlink(link)
                lines.append(f"Removed {link}")
        folder = str(remove.get("dir") or "")
        if folder and os.path.isdir(folder) and not os.path.islink(folder):
            shutil.rmtree(folder)
            lines.append(f"Removed {folder}")
    except OSError as exc:
        lines.append(_reason(exc))
        return 1, "\n".join(lines)
    return 0, "\n".join(lines)


# ── installing a missing CLI (Settings › Agents) ──
# Each vendor's documented installer, the same ones a host's own install script offers: Claude
# Code, Cursor and Antigravity from their install scripts (WinGet for Antigravity on Windows),
# the npm-published ones with the npm on this machine. The page only names the command; these
# strings are fixed here, never built from the request.

INSTALL_SCRIPTS = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "agent": "curl -fsS https://cursor.com/install | bash",
    "agy": "curl -fsSL https://antigravity.google/cli/install.sh | bash",
}
WINDOWS_INSTALL_SCRIPTS = {
    "claude": "irm https://claude.ai/install.ps1 | iex",
    "agent": "irm 'https://cursor.com/install?win32=true' | iex",
}
WINGET_INSTALLS = {"agy": "Google.AntigravityCLI"}
# Google's documented script, used only when WinGet cannot be found (it goes through the
# WinINET proxy, which a corporate laptop may refuse with a 407 that WinGet does not hit).
WINDOWS_FALLBACK_SCRIPTS = {"agy": "irm https://antigravity.google/cli/install.ps1 | iex"}
INSTALL_NPM_PACKAGES = {command: NPM_PACKAGES[command] for command in ("gemini", "copilot", "grok", "opencode")}
_NPM_PLACES = ("/opt/homebrew/bin/npm", "/usr/local/bin/npm")
_BREW_PLACES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")


def install_plan(
    command: str,
    *,
    is_windows: bool = False,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    find: Callable[[list[str]], str] = first_executable,
) -> dict[str, Any]:
    """How to install a missing ``command``: ``{argv, then, how, manual?}``, or ``{argv: [], hint}``.

    ``manual`` is the command line the owner can run by hand if ``argv`` fails. On Windows
    PowerShell and WinGet are found by full path too (a background node's PATH may lack them).

    npm comes from the PATH, else Homebrew's or ``~/.local/bin`` (where a host's installer puts
    Node.js); with no npm but Homebrew, Node.js is installed first (``then`` runs after ``argv``).
    """
    if is_windows:
        script = WINDOWS_INSTALL_SCRIPTS.get(command, "")
        if command in WINGET_INSTALLS:
            winget = which("winget") or find(windows_places("LOCALAPPDATA", r"Microsoft\WindowsApps\winget.exe"))
            package_id = WINGET_INSTALLS[command]
            if winget:
                argv = [
                    winget, "install", "-e", "--id", package_id, "--source", "winget",
                    "--silent", "--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements",
                ]
                return {"argv": argv, "then": [], "how": "WinGet", "manual": f"winget install -e --id {package_id}"}
            # No WinGet (App Installer removed, or out of a background process's reach): the
            # vendor's own PowerShell script instead.
            script = WINDOWS_FALLBACK_SCRIPTS.get(command, "")
            if not script:
                return {"argv": [], "hint": f"install App Installer (WinGet), then: winget install -e --id {package_id}"}
        if script:
            powershell = which("powershell") or find(
                windows_places("SystemRoot", r"System32\WindowsPowerShell\v1.0\powershell.exe")
            )
            if not powershell:
                return {"argv": [], "hint": f"in a PowerShell window: {script}"}
            argv = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
            return {"argv": argv, "then": [], "how": "its install script", "manual": script}
        package = INSTALL_NPM_PACKAGES.get(command)
        if not package:
            return {"argv": [], "hint": f"no installer is known for {command!r}"}
        npm = which("npm.cmd") or which("npm") or ""
        if not npm:
            return {"argv": [], "hint": f"install Node.js (https://nodejs.org), then: npm install -g {package}"}
        return {"argv": [npm, "install", "-g", package], "then": [], "how": "npm"}
    if command in INSTALL_SCRIPTS:
        return {"argv": ["/bin/bash", "-c", INSTALL_SCRIPTS[command]], "then": [], "how": "its install script"}
    package = INSTALL_NPM_PACKAGES.get(command)
    if not package:
        return {"argv": [], "hint": f"no installer is known for {command!r}"}
    local_npm = str((home or Path.home()) / ".local" / "bin" / "npm")
    npm = which("npm") or find([*_NPM_PLACES, local_npm])
    if npm:
        return {"argv": [npm, "install", "-g", package], "then": [], "how": "npm"}
    brew = which("brew") or find(list(_BREW_PLACES))
    if brew:
        npm = str(Path(brew).parent / "npm")
        return {"argv": [brew, "install", "node"], "then": [[npm, "install", "-g", package]], "how": "Homebrew Node.js, then npm"}
    return {"argv": [], "hint": f"install Node.js (https://nodejs.org), then: npm install -g {package}"}


class ClaudeReleaseError(Exception):
    """Anthropic's binary could not be installed over the Homebrew cask. The old file is untouched."""


def is_claude_cask_binary(resolved: str) -> bool:
    """``True`` when ``resolved`` is the ``claude`` file of a Claude Code Homebrew cask (stable or ``@latest``)."""
    path = Path(resolved) if resolved else None
    if path is None or not path.is_absolute() or path.name != "claude" or "Caskroom" not in path.parts:
        return False
    at = path.parts.index("Caskroom")
    return at + 1 < len(path.parts) and path.parts[at + 1] in (CLAUDE_LATEST_CASK, *CASK_LATEST_TWIN)


def is_claude_latest_cask_binary(resolved: str) -> bool:
    """``True`` when ``resolved`` is the ``claude`` file inside ``Caskroom/claude-code@latest``."""
    path = Path(resolved)
    parts = path.parts
    if not path.is_absolute() or path.name != "claude" or "Caskroom" not in parts:
        return False
    at = parts.index("Caskroom")
    return at + 1 < len(parts) and parts[at + 1] == CLAUDE_LATEST_CASK


def claude_release_url(version: str, system: str, machine: str) -> str:
    """The binary URL the ``claude-code@latest`` cask itself uses for this machine."""
    if not _PLAIN_VERSION.match(version or ""):
        raise ClaudeReleaseError(f"refusing a Claude release version that is not a plain number: {version!r}")
    os_name = _RELEASE_OS.get(system, "")
    arch = _RELEASE_ARCH.get(machine, "")
    if not os_name or not arch:
        raise ClaudeReleaseError(f"no Claude Code build is published for {system} {machine}")
    return f"https://{CLAUDE_RELEASE_HOST}/claude-code-releases/{version}/{os_name}-{arch}/claude"


def published_claude_version(fetch: Callable[[str], bytes] = fetch_text) -> str:
    """The version Anthropic is serving at ``.../claude-code-releases/latest`` (plain text)."""
    try:
        body = fetch(CLAUDE_RELEASE_LATEST_URL)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ClaudeReleaseError(f"could not read Anthropic's latest Claude version: {_reason(exc)}") from exc
    version = parse_version(body.decode("utf-8", "replace"))
    if not _PLAIN_VERSION.match(version):
        raise ClaudeReleaseError("Anthropic's latest release did not name a version")
    return version


def _download_claude_release(url: str, dest: Path, *, timeout: float = 120.0) -> None:
    """Stream one Claude binary to ``dest``. The caller deletes ``dest`` if anything after this fails."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != CLAUDE_RELEASE_HOST:
        raise ClaudeReleaseError("refusing a Claude download that is not https://downloads.claude.ai")
    total = 0
    try:
        with open_limited(url, timeout=timeout, headers={"User-Agent": USER_AGENT}) as response:
            announced = response.headers.get("Content-Length")
            if announced and announced.isdigit():
                size = int(announced)
                if size < CLAUDE_RELEASE_MIN_BYTES or size > CLAUDE_RELEASE_MAX_BYTES:
                    raise ClaudeReleaseError(
                        f"Anthropic announced a Claude binary of {size} bytes, which is not a release"
                    )
            with dest.open("wb") as out:
                try:
                    total, _body = read_bounded(response, CLAUDE_RELEASE_MAX_BYTES, out)
                except ValueError:
                    raise ClaudeReleaseError("Anthropic's Claude binary is larger than expected") from None
    except ClaudeReleaseError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ClaudeReleaseError(f"could not download Claude Code: {_reason(exc)}") from exc
    if total < CLAUDE_RELEASE_MIN_BYTES:
        raise ClaudeReleaseError(f"Anthropic's Claude binary is only {total} bytes")

def clear_macos_quarantine(path: str) -> bool:
    """Drop Gatekeeper's download mark from one CLI binary. ``False`` when there was nothing to drop.

    No-op off macOS, and when the attribute is already absent. A failure to remove it is reported
    as ``False`` (the update still stands); the caller logs it. Only this one attribute is
    removed — other extended attributes stay.
    """
    if platform.system() != "Darwin" or not path:
        return False
    try:
        target = os.path.realpath(path)
    except OSError:
        return False
    if not os.path.isfile(target):
        return False
    try:
        probe = subprocess.run(  # noqa: S603 — fixed xattr argv, path is a CLI this host already runs
            ["/usr/bin/xattr", "-p", QUARANTINE_ATTR, target],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if probe.returncode != 0:
            return False
        cleared = subprocess.run(  # noqa: S603 — same as above
            ["/usr/bin/xattr", "-d", QUARANTINE_ATTR, target],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return cleared.returncode == 0


def verify_claude_signature(path: str) -> None:
    """The download is Anthropic's build: Mach-O + their team id on macOS, ELF on Linux."""
    try:
        header = Path(path).read_bytes()[:4]
        system = platform.system()
        if system == "Darwin":
            if header != b"\xcf\xfa\xed\xfe":
                raise ClaudeReleaseError("the downloaded Claude binary is not a macOS executable")
            verified = subprocess.run(  # noqa: S603 — fixed codesign argv, path is the temp download
                ["/usr/bin/codesign", "--verify", "--strict", path],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if verified.returncode != 0:
                detail = (verified.stderr or verified.stdout or "codesign --verify failed").strip()
                raise ClaudeReleaseError(f"Anthropic's signature check failed: {detail}")
            info = subprocess.run(  # noqa: S603 — same as above
                ["/usr/bin/codesign", "-d", "--verbose=4", path],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            text = f"{info.stdout}\n{info.stderr}"
            if f"Identifier={ANTHROPIC_SIGN_ID}" not in text or f"TeamIdentifier={ANTHROPIC_TEAM_ID}" not in text:
                raise ClaudeReleaseError("the downloaded Claude binary is not signed by Anthropic")
            return
        if system == "Linux":
            if header != b"\x7fELF":
                raise ClaudeReleaseError("the downloaded Claude binary is not a Linux executable")
            return
        raise ClaudeReleaseError(f"no Claude signature check for {system}")
    except ClaudeReleaseError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClaudeReleaseError(f"could not check the Claude signature: {_reason(exc)}") from exc


def install_published_claude(
    dest: str,
    version: str,
    *,
    system: str | None = None,
    machine: str | None = None,
    download: Callable[[str, Path], None] | None = None,
    verify: Callable[[str], None] | None = None,
) -> str:
    """Replace the ``claude-code@latest`` cask file with Anthropic's published ``version``.

    ``brew upgrade`` cannot install a release Homebrew has not put in the formula yet. The
    symlink (``/opt/homebrew/bin/claude``) keeps pointing at this same file. A failed download
    or a failed signature check deletes the temp file and leaves ``dest`` as it was.
    """
    path = Path(dest)
    if path.is_symlink() or not path.is_file() or not is_claude_latest_cask_binary(str(path.resolve())):
        raise ClaudeReleaseError("refusing to replace a Claude binary that is not the claude-code@latest cask file")
    url = claude_release_url(version, system or platform.system(), machine or platform.machine())
    fetch = download or _download_claude_release
    check = verify or verify_claude_signature
    tmp = path.with_name(DOWNLOAD_NAME)
    try:
        fetch(url, tmp)
        if not tmp.is_file():
            raise ClaudeReleaseError("the Claude download wrote nothing")
        os.chmod(tmp, 0o755)
        check(str(tmp))
        os.replace(tmp, path)
        # A download can arrive already quarantined. The cask symlink still points here, so the
        # mark has to be gone before the next launch or Gatekeeper offers to trash `claude`.
        clear_macos_quarantine(str(path))
    except ClaudeReleaseError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ClaudeReleaseError(f"could not install Claude Code {version}: {_reason(exc)}") from exc
    return f"Installed Anthropic's Claude Code {version} over the Homebrew cask (its formula was still behind)."


def catch_up_claude_cask(
    resolved: str,
    installed: str,
    npm_latest: str,
    *,
    fetch: Callable[[str], bytes] = fetch_text,
    install: Callable[[str, str], str] | None = None,
) -> tuple[int, str]:
    """When ``brew upgrade`` left the ``@latest`` cask behind npm, install Anthropic's binary.

    Returns ``(0, "")`` when there is nothing to do, ``(0, note)`` when the binary was replaced,
    ``(1, note)`` when the update the desk promised cannot be done.
    """
    if not is_claude_latest_cask_binary(resolved) or is_outdated(installed, npm_latest) is not True:
        return 0, ""
    try:
        published = published_claude_version(fetch)
    except ClaudeReleaseError as exc:
        have = installed or "an unknown version"
        return 1, f"Homebrew left Claude Code at {have}. {exc}"
    if is_outdated(installed, published) is not True:
        shown = published or "not newer"
        return 1, (
            f"Homebrew's claude-code@latest cask is already at {installed}, and Anthropic's "
            f"download is {shown}. npm advertises {npm_latest}, which is not a binary either of them is offering yet."
        )
    installer = install if install is not None else install_published_claude
    try:
        return 0, installer(resolved, published)
    except ClaudeReleaseError as exc:
        return 1, str(exc)


def run_update(argv: list[str], timeout: float = UPDATE_TIMEOUT) -> tuple[int, str]:
    """Run one update argv (no shell) and return its exit code and the tail of its output."""
    if os.name == "nt":
        argv = [shutil.which(argv[0]) or argv[0], *argv[1:]]
    env = dict(os.environ)
    # A LaunchAgent starts with a bare PATH: npm needs the `node` beside it, brew its own bin.
    env["PATH"] = os.pathsep.join([str(Path(argv[0]).parent), env.get("PATH", "")])
    env.setdefault("HOMEBREW_NO_ENV_HINTS", "1")
    try:
        completed = subprocess.run(  # noqa: S603 — argv built by update_plan, never from a request
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
            **background_process_options(),
        )
    except subprocess.TimeoutExpired:
        return -1, f"Gave up after {timeout:.0f}s."
    except OSError as exc:
        return -1, f"Could not start {argv[0]}: {_reason(exc)}"
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
    return completed.returncode, output[-_OUTPUT_TAIL:]
