"""Registry of local AI coding CLIs the bridge can spawn.

Every entry uses the vendor's official binary through its documented headless
interface, authenticated by the user's own login (OAuth/keychain). The bridge
never calls vendor backend APIs directly and never extracts tokens — that is
the compliance line this project is built around.

Flavors must stay in sync with the adapters in runner.py / argv.py.
"""
import contextlib
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CliAgentSpec:
    """A local CLI coding agent the bridge knows how to spawn."""

    command: str  # canonical command name (also the bridge's agent id)
    name: str  # display name
    flavor: str  # spawn/stream adapter: claude | cursor | antigravity | gemini | grok | copilot | opencode
    aliases: tuple[str, ...]  # PATH / well-known names to resolve
    app_markers: tuple[str, ...] = ()  # IDE app paths that count as "installed"
    install_hint: str = ""
    # Curated model list surfaced to pickers AND passed verbatim to the CLI
    # via ``--model <id>``. Keep ids ≤ the CLI's own vocabulary so the
    # subprocess never rejects the argument. First entry is the default.
    models: tuple[str, ...] = ()
    # ``True`` iff the CLI's argv layer supports ``--model``. When False the
    # model id is display-only and the flag is omitted at spawn time.
    supports_model_flag: bool = True


CLI_AGENT_SPECS: tuple[CliAgentSpec, ...] = (
    CliAgentSpec(
        command="claude",
        name="Claude Code",
        flavor="claude",
        aliases=("claude",),
        install_hint="Install Claude Code: https://claude.ai/code",
        # `claude --model` accepts short aliases (verified) or full ids.
        # The aliases always resolve to the latest release (`fable` is the
        # flagship tier, `haiku` the fastest). `claude-opus-5-5` pins Opus 5.5
        # by its full id (Claude Code >= 2.1.280 — older builds list it as
        # "Opus 5.5 (disabled)"); append `[1m]` for the 1M-context variant.
        models=("sonnet", "fable", "opus", "claude-opus-5-5", "haiku"),
    ),
    CliAgentSpec(
        command="agent",
        name="Cursor Agent",
        flavor="cursor",
        aliases=("agent", "cursor-agent"),
        app_markers=("/Applications/Cursor.app",),
        install_hint="Install Cursor Agent CLI: curl https://cursor.com/install -fsS | bash",
        # A curated shortlist of current flagships from `cursor-agent models`
        # (verified 2026-09-30; the CLI exposes ~245 ids across effort/fast
        # tiers). "auto" lets Cursor pick; parameterized overrides (e.g.
        # claude-opus-5[effort=high]) can be passed via cli_args.
        models=(
            "auto",
            "composer-2.5",
            "grok-4.7-high",
            "cursor-grok-4.6-high",
            "claude-opus-5-5-high",
            "claude-fable-5-1-high",
            "claude-sonnet-5-5-high",
            "claude-opus-5-thinking-high",
            "gpt-5.6-sol-high",
            "gpt-5.3-codex",
        ),
    ),
    CliAgentSpec(
        command="agy",
        name="Google Antigravity",
        flavor="antigravity",
        aliases=("agy",),
        app_markers=("/Applications/Antigravity.app",),
        install_hint=(
            "Install Antigravity CLI: "
            "curl -fsSL https://antigravity.google/cli/install.sh | bash "
            "(Windows: winget install -e --id Google.AntigravityCLI)"
        ),
        # Ids match `agy models` (verified 2026-08-27, CLI 1.1.22). "default"
        # is kept first so existing settings that stored it still resolve to
        # the CLI's own default.
        models=(
            "default",
            "gemini-3.1-pro-high",
            "gemini-3.1-pro-low",
            "gemini-3.7-flash-high",
            "gemini-3.7-flash-medium",
            "gemini-3.7-flash-low",
            "gemini-3.6-flash-high",
            "gemini-3.6-flash-medium",
            "gemini-3.6-flash-low",
            "gemini-3.5-flash-high",
            "gemini-3.5-flash-medium",
            "gemini-3.5-flash-low",
            "claude-sonnet-4-6",
            "claude-opus-4-6-thinking",
            "gpt-oss-120b-medium",
        ),
    ),
    CliAgentSpec(
        command="grok",
        name="Grok CLI",
        flavor="grok",
        aliases=("grok",),
        install_hint="Install Grok CLI: npm install -g @xai-official/grok",
        models=("grok-4.6", "grok-4.6-high", "grok-4.5"),
    ),
    CliAgentSpec(
        command="gemini",
        name="Gemini CLI",
        flavor="gemini",
        aliases=("gemini",),
        install_hint=(
            "Install Gemini CLI: npm install -g @google/gemini-cli — then run "
            "`gemini` once and choose 'Login with Google' (no API key needed)."
        ),
        # Ids match the CLI's own vocabulary (`gemini --help`).
        models=(
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ),
    ),
    CliAgentSpec(
        command="copilot",
        name="GitHub Copilot CLI",
        flavor="copilot",
        aliases=("copilot",),
        install_hint=(
            "Install GitHub Copilot CLI: npm install -g @github/copilot — then "
            "run `copilot` once to sign in with your GitHub account."
        ),
        # "auto" lets Copilot pick (documented in --help); claude-sonnet-5 is
        # the observed default; gpt-5-mini is an included (non-premium) model.
        models=("auto", "claude-sonnet-5", "gpt-5-mini"),
    ),
    CliAgentSpec(
        command="opencode",
        # OpenCode is used here as the OpenRouter client: the CLI is `opencode`, the UI says Open Router.
        name="Open Router",
        flavor="opencode",
        aliases=("opencode",),
        install_hint=(
            "Install OpenCode: brew install opencode — then run "
            "`opencode auth login -p openrouter` to store your OpenRouter key."
        ),
        # Ids are `provider/model` (`opencode models`). OpenRouter's free and stealth
        # models come and go: list current ones in agent_cli_bridge.json (see config_path)
        # ("models": {"opencode": [...]}). opencode/big-pickle is OpenCode Zen's free
        # model and needs no key.
        models=("openrouter/stealth/union-alpha", "opencode/big-pickle"),
    ),
)

_BY_COMMAND: dict[str, CliAgentSpec] = {spec.command: spec for spec in CLI_AGENT_SPECS}
for _spec in CLI_AGENT_SPECS:
    for _alias in _spec.aliases:
        _BY_COMMAND.setdefault(_alias, _spec)


def cli_agent_spec(command: str) -> CliAgentSpec | None:
    """Return the spec for a command or alias, if known."""
    return _BY_COMMAND.get((command or "").strip())


def _usable(path: Path) -> bool:
    # is_file() traverses symlinks, so a dangling link returns False —
    # spawning a broken symlink would fail with ENOENT at chat time.
    return path.is_file() and os.access(path, os.X_OK)


def _probe(path: Path) -> str | None:
    """Return path if it is a usable binary, also trying ``.exe`` on Windows."""
    candidates = [path]
    if path.suffix.lower() != ".exe":
        candidates.append(path.with_name(path.name + ".exe"))
    for candidate in candidates:
        if _usable(candidate):
            return str(candidate)
    return None


def resolve_binary(command: str) -> str | None:
    """Resolve a CLI agent binary path (PATH, ~/.local/bin, versioned installs).

    Also probes vendor-specific fallback dirs when the flavor is known —
    currently ``~/.local/share/cursor-agent/versions/<ver>/`` for Cursor
    Agent and Antigravity's macOS ``~/.antigravity/Antigravity/bin/`` plus
    the Windows official layout ``%LOCALAPPDATA%/agy/bin/``. Dangling
    symlinks (target missing) return None so callers report the CLI as "not
    installed" instead of "installed at <broken path>".
    """
    command = (command or "").strip()
    if not command:
        return None
    spec = cli_agent_spec(command)
    aliases = spec.aliases if spec else (command,)
    home = Path.home()

    for alias in aliases:
        path = shutil.which(alias)
        if path:
            return path
        found = _probe(home / ".local" / "bin" / alias)
        if found:
            return found

    if command in ("agent", "cursor-agent") or (spec and spec.flavor == "cursor"):
        versions = home / ".local" / "share" / "cursor-agent" / "versions"
        if versions.is_dir():
            for version_dir in sorted(versions.iterdir(), reverse=True):
                for name in ("agent", "cursor-agent"):
                    found = _probe(version_dir / name)
                    if found:
                        return found

    if spec and spec.flavor == "antigravity":
        local_app = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else home / "AppData" / "Local"
        for candidate in (
            home / ".antigravity" / "Antigravity" / "bin" / "agy",
            local_app / "agy" / "bin" / "agy",
        ):
            found = _probe(candidate)
            if found:
                return found

    return None


def app_installed(spec: CliAgentSpec) -> bool:
    """True when the vendor IDE app is present (CLI may still be missing)."""
    return any(Path(marker).exists() for marker in spec.app_markers)


CONFIG_FILE = "agent_cli_bridge.json"
APP_NAME = "AgentCliBridge"
CONFIG_LOCAL_ENV = "AGENT_CLI_BRIDGE_CONFIG_LOCAL"
CONFIG_LOCAL_FOLDER = "config.local"
LOCAL_ONLY = "none"


def _package_checkout() -> Path:
    """The folder above this package: the checkout when it runs from source, site-packages otherwise."""
    return Path(__file__).resolve().parents[1]


def _is_bridge_checkout(folder: Path) -> bool:
    """``folder`` is an AgentCliBridge source checkout: this package beside a pyproject.toml naming it."""
    try:
        if not (folder / "agent_cli_bridge" / "specs.py").is_file():
            return False
        pyproject = (folder / "pyproject.toml").read_text(encoding="utf-8")
    except (OSError, ValueError):  # missing, unreadable or not UTF-8
        return False
    return f'name = "{APP_NAME}"' in pyproject


def bridge_checkout() -> Path | None:
    """The AgentCliBridge checkout whose ``config.local/`` holds the owner's settings, if one is found.

    Every app built on the bridge reads the same file, so this is always the bridge's checkout,
    never the consuming app's:

    1. the checkout this code runs from (the gateway, an editable install);
    2. else, installed into an app's venv (``<app>/.venv``), the sibling ``<app>/../AgentCliBridge``:
       the code root the app itself lives in, so two roots on one machine never mix;
    3. else ``$AI_CODE_ROOT/AgentCliBridge`` (``~/Code``, then ``~/CODE``, when unset).

    A folder counts only when it looks like the real checkout (package + pyproject.toml).
    """
    candidates = [_package_checkout(), Path(sys.prefix).parent.parent / APP_NAME]
    root = os.environ.get("AI_CODE_ROOT", "").strip()
    with contextlib.suppress(RuntimeError):  # no home directory to expand
        if root:
            candidates.append(Path(root).expanduser() / APP_NAME)
        else:
            home = Path.home()
            candidates.extend(home / name / APP_NAME for name in ("Code", "CODE"))
    for folder in candidates:
        if _is_bridge_checkout(folder):
            return folder
    return None


def config_local_dir() -> Path | None:
    """The folder whose ``agent_cli_bridge.json`` holds the owner's shared settings; None = local only.

    ``$AGENT_CLI_BRIDGE_CONFIG_LOCAL`` when set (empty or ``none`` = local only), else the
    ``config.local/`` of ``bridge_checkout()``. The folder may not exist: nothing creates it but
    the one-time migration below.
    """
    pinned = os.environ.get(CONFIG_LOCAL_ENV)
    if pinned is not None:
        pinned = pinned.strip()
        if not pinned or pinned == LOCAL_ONLY:
            return None
        try:
            return Path(pinned).expanduser()
        except RuntimeError:  # "~/…" with no home directory: take it as written
            return Path(pinned)
    checkout = bridge_checkout()
    return checkout / CONFIG_LOCAL_FOLDER if checkout is not None else None


# legacy apps-config migration — remove after 2027-01
# Until config.local/, the settings lived in <apps-config root>/AgentCliBridge/ (a synced folder
# named by $APPS_CONFIG_DIR or ~/.apps-config-dir). The one-time copy below is its only reader.
def apps_config_dir(app: str = APP_NAME) -> Path | None:
    """<root>/<app> of the retired apps-config folder, when it exists, else None.

    ``<root>`` is ``$APPS_CONFIG_DIR``, else the first line of ``~/.apps-config-dir``; empty or
    ``none`` disables the lookup. Read only by ``migrate_legacy_settings``.
    """
    root = os.environ.get("APPS_CONFIG_DIR")
    if root is None:
        try:
            lines = (Path.home() / ".apps-config-dir").read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        root = lines[0] if lines else ""
    root = root.strip()
    if not root or root == LOCAL_ONLY:
        return None
    folder = Path(root).expanduser() / app
    try:
        return folder if folder.is_dir() else None
    except OSError:  # an online-only cloud placeholder
        return None


def migrate_legacy_settings(target: Path) -> Path | None:
    """Copy ``agent_cli_bridge.json`` from the retired apps-config folder into ``target``, once.

    Only while ``target`` has no settings file; never overwrites, never deletes the source; the
    copy goes through a temp file so half a copy never looks like settings. Returns the file
    copied, None when there was nothing to copy; raises OSError when the copy failed.
    """
    if (target / CONFIG_FILE).exists():
        return None
    legacy = apps_config_dir()
    if legacy is None or not (legacy / CONFIG_FILE).is_file():
        return None
    target.mkdir(parents=True, exist_ok=True)
    # a temp name of its own: a gateway and an app starting together never remove each other's
    fd, name = tempfile.mkstemp(prefix=f".{CONFIG_FILE}.", suffix=".migrating", dir=target)
    os.close(fd)
    temp = Path(name)
    try:
        shutil.copyfile(legacy / CONFIG_FILE, temp)
        os.replace(temp, target / CONFIG_FILE)
    finally:
        temp.unlink(missing_ok=True)
    return legacy / CONFIG_FILE


_migration_tried: set[Path] = set()


def _migrate_once(target: Path) -> None:
    """``migrate_legacy_settings`` the first time this process reads ``target``; never raises."""
    if target in _migration_tried:
        return
    _migration_tried.add(target)
    try:
        source = migrate_legacy_settings(target)
    except OSError as exc:  # a cloud placeholder can stat fine and still fail to open
        log.warning("AgentCliBridge: could not copy the old settings into %s: %s", target, exc)
        return
    if source is not None:
        log.info("AgentCliBridge: copied %s from the old apps-config folder into %s", CONFIG_FILE, target)


def config_path() -> Path:
    """The settings file ``discover_agents`` reads and ``enable_agents`` writes back.

    ``<config.local>/agent_cli_bridge.json`` (``config_local_dir()``) when that file exists, else
    the local-only ``~/.agent_cli_bridge.json``; neither exists → built-in defaults. A checkout's
    config.local first gets the one-time copy from the retired apps-config folder.
    """
    folder = config_local_dir()
    if folder is not None:
        if os.environ.get(CONFIG_LOCAL_ENV) is None:
            _migrate_once(folder)
        candidate = folder / CONFIG_FILE
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            pass
    return Path.home() / f".{CONFIG_FILE}"


def load_config() -> dict[str, Any]:
    """The settings as a dict; ``{}`` when the file is missing, unreadable or not JSON."""
    import json

    try:
        with open(config_path(), encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def _disabled_names(config: dict[str, Any]) -> list[str]:
    """The string entries of ``disabled_agents``; a value that is not a list names nothing."""
    listed = config.get("disabled_agents")
    return [item for item in listed if isinstance(item, str)] if isinstance(listed, list) else []


def _custom_models(config: dict[str, Any], *keys: str) -> list[str] | None:
    """The settings' ``models`` override for the first of ``keys`` that has a list of model names."""
    table = config.get("models")
    for key in keys:
        names = table.get(key) if isinstance(table, dict) else None
        if isinstance(names, list):
            return [name for name in names if isinstance(name, str) and name]
    return None


def disabled_agents() -> set[str]:
    """Commands or flavors the settings file (``config_path()``) turns off: never listed, never offered."""
    return set(_disabled_names(load_config()))


def enable_agents(names: set[str]) -> None:
    """Drop ``names`` (commands or flavors) from the settings file's ``disabled_agents``.

    The rest of the file is kept as it is; nothing is written when none of them is listed. Written
    through a temporary file so a reader never sees half of it.
    """
    import json

    config = load_config()
    listed = _disabled_names(config)
    kept = [item for item in listed if item not in names]
    if kept == listed:
        return
    config["disabled_agents"] = kept
    path = config_path()
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def discover_agents() -> list[dict[str, Any]]:
    """Return CLI agents found on PATH, well-known paths, or via IDE apps.

    Filters disabled agents and overrides models from the settings file (``config_path()``).
    """
    config = load_config()

    disabled = set(_disabled_names(config))

    found: list[dict[str, Any]] = []
    for spec in CLI_AGENT_SPECS:
        if spec.command in disabled or spec.flavor in disabled:
            continue

        binary = resolve_binary(spec.command)
        ide_present = app_installed(spec)
        if not binary and not ide_present:
            continue

        models = _custom_models(config, spec.command, spec.flavor) or list(spec.models) or [spec.command]

        found.append(
            {
                "command": spec.command,
                "name": spec.name,
                "path": binary,
                "flavor": spec.flavor,
                "models": models,
                "supports_model_flag": spec.supports_model_flag,
                "binary_found": bool(binary),
                "install_hint": spec.install_hint if not binary else "",
            }
        )
    return found


def is_cursor_grok_collision(agent: dict[str, Any]) -> bool:
    """Cursor's generic ``agent`` alias resolving to Grok CLI's own binary (``.grok/bin``).

    Such an entry is Grok, not Cursor: listing it as Cursor, or running or updating it as
    Cursor, would drive the wrong CLI. Grok's own entry is never a collision. Either slash
    style, on any host OS.
    """
    command = str(agent.get("command") or "").strip().lower()
    flavor = str(agent.get("flavor") or "").strip().lower()
    if command not in {"agent", "cursor-agent"} and flavor != "cursor":
        return False
    parts = tuple(p.lower() for p in PureWindowsPath(str(agent.get("path") or "")).parts)
    return any(parts[i : i + 2] == (".grok", "bin") for i in range(len(parts) - 1))


def is_available(agent: dict[str, Any]) -> bool:
    """Whether a host offers this ``discover_agents`` entry: a CLI binary, no Cursor/Grok collision.

    The picker rule every app built on AgentCliBridge shares; change it here and they all follow.
    (Disabled agents never reach this point: ``discover_agents`` already leaves them out.)
    """
    return bool(agent.get("binary_found")) and not is_cursor_grok_collision(agent)


def available_agents() -> list[dict[str, Any]]:
    """The agents a host offers the user: what ``discover_agents`` finds with a binary.

    One rule for every app built on AgentCliBridge, so their pickers list the same agents:
    ``disabled_agents`` of the settings file (``config_path()``) are left out, an IDE-only install
    (no CLI binary) is left out, and a Cursor/Grok collision is left out. Same dicts as
    ``discover_agents``, in the registry's order.
    """
    return [a for a in discover_agents() if is_available(a)]


def flavor_for(command: str) -> str:
    """Map a command to its spawn/stream adapter flavor (default: claude)."""
    spec = cli_agent_spec(command)
    return spec.flavor if spec else "claude"
