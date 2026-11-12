"""Headless argv construction per CLI flavor.

Every flag used here is documented by the vendor (``--help`` / official docs):
Claude Code ``-p --output-format stream-json``, Cursor Agent
``-p --output-format stream-json --stream-partial-output``, Gemini CLI
``-p --output-format stream-json``, Antigravity ``-p --add-dir <cwd>``, OpenCode
``run --format json``.
No undocumented switches.
"""
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Claude Code --permission-mode values (claude --help). The default for a
# headless chat backend is acceptEdits: Write/Edit work without an interactive
# prompt the host UI can't answer. "manual" will stall on gated tools in -p
# mode; it is exposed for completeness.
PERMISSION_MODES = (
    "plan",
    "manual",
    "acceptEdits",
    "auto",
    "dontAsk",
    "bypassPermissions",
)
DEFAULT_PERMISSION_MODE = "acceptEdits"


# Grok built-ins that cannot change anything (internal tool ids from the `grok -p` init
# line). MCP meta-tools (search_tool / use_tool) are always added, hence `--deny MCPTool`.
GROK_READ_ONLY_TOOLS = "read_file,list_dir,grep,todo_write,web_search,web_fetch"
# The edit modes add only the two file-edit built-ins: no shell, monitor, workflow, kill or
# paid image/video tool, since `--always-approve` would run whatever is left unasked.
GROK_EDIT_TOOLS = f"{GROK_READ_ONLY_TOOLS},search_replace,write"
# CLIs that can read a one-shot prompt from stdin instead of their argv (``prompt_on_stdin``).
STDIN_PROMPT_FLAVORS = frozenset({"claude", "grok"})


def normalize_permission_mode(mode: str | None) -> str:
    """Return a known permission mode.

    ``None`` means the caller omitted the mode and stays ``acceptEdits``. Any
    other value that is not one of ``PERMISSION_MODES`` — including ``""`` and
    ``"Plan"`` — becomes ``plan`` and is logged. An unknown mode must not fall
    through to a mode that can edit.
    """
    if mode is None:
        return DEFAULT_PERMISSION_MODE
    raw = mode.strip()
    if raw in PERMISSION_MODES:
        return raw
    log.warning("unknown permission mode %r; using plan", raw)
    return "plan"


def permission_args(flavor: str, permission_mode: str | None) -> list[str]:
    """Map the host's permission mode onto CLI argv flags.

    Claude Code understands ``--permission-mode`` directly. Cursor Agent has
    no equivalent vocabulary — ``--force`` / ``--trust`` cover the
    non-interactive write path for every mode except Plan/Ask (where
    ``--force`` is omitted so the agent stays read-leaning). Gemini maps to
    ``--approval-mode`` (plan = read-only, yolo = auto-approve). Antigravity
    maps to ``--mode`` (plan = plan, others = accept-edits). Grok restricts its
    tools instead of trusting its own modes (GROK_READ_ONLY_TOOLS, GROK_EDIT_TOOLS)
    and approves what is left with ``--always-approve``, so a headless ask cannot
    cancel the turn.
    """
    mode = normalize_permission_mode(permission_mode)
    if flavor == "claude":
        args = ["--permission-mode", mode]
        # Bypass needs the companion allow flag on some Claude builds before
        # --permission-mode bypassPermissions is honoured in -p.
        if mode == "bypassPermissions":
            args.append("--dangerously-skip-permissions")
        return args
    if flavor == "cursor":
        if mode in ("plan", "manual"):
            return ["--trust"]  # workspace trust only; no --force
        return ["--trust", "--force"]
    if flavor == "grok":
        # `--permission-mode plan` is only "accepted for compatibility": Grok still edits
        # files and runs commands. And a headless Grok cancels its whole turn when a tool
        # needs an approval nobody can give. So restrict tools instead (verified live
        # 2026-09-14): Plan/Ask keep read-only built-ins; the edit modes allow edits but
        # deny the shell, MCP tools and subagents, which the agent sees as a refusal and
        # works around, rather than as a prompt that ends the turn.
        if mode in ("plan", "manual"):
            return ["--tools", GROK_READ_ONLY_TOOLS, "--disallowed-tools", "Agent", "--deny", "MCPTool"]
        if mode == "bypassPermissions":
            return ["--permission-mode", mode]
        if mode == "auto":
            # Grok's own `auto` still asks for some calls (an edit, a command it will not
            # just block). A headless run cannot answer, and grok 1.0.52 then cancels the
            # whole turn (stop_reason "cancelled", cancellationCategory PermissionCancelled)
            # instead of telling the model "Auto mode blocked …" and carrying on.
            # `--always-approve` is the mode grok documents for a headless agent: tools run,
            # and deny rules plus shell ask rules still apply.
            return ["--always-approve"]
        # Accept edits / dontAsk / default. grok 1.0.77 `--permission-mode acceptEdits` still
        # asks before every `search_replace` headless, and the turn is cancelled (verified live
        # 2026-11-10). So keep only read and edit tools, and approve those.
        return [
            "--tools", GROK_EDIT_TOOLS,
            "--disallowed-tools", "Agent", "--deny", "Bash", "--deny", "MCPTool",
            "--always-approve",
        ]

    if flavor == "opencode":
        # `opencode run` rejects any tool call that would ask for approval, and the
        # turn then ends without an answer. Plan/Ask use its built-in `plan` agent
        # (edits denied, verified live 2026-09-17); the default `build` agent asks
        # nothing inside the project directory; Bypass also approves the rest
        # (paths outside it).
        if mode in ("plan", "manual"):
            return ["--agent", "plan"]
        if mode == "bypassPermissions":
            return ["--auto"]
        return []
    if flavor == "gemini":
        if mode in ("plan", "manual"):
            return ["--approval-mode", "plan"]
        return ["--approval-mode", "yolo"]
    if flavor == "copilot":
        # copilot --help: --plan starts read-only plan mode;
        # --allow-all-tools is required for tool use in non-interactive mode.
        if mode == "plan":
            return ["--plan"]
        return ["--allow-all-tools"]
    if flavor == "antigravity":
        if mode == "bypassPermissions":
            return ["--mode", "accept-edits", "--dangerously-skip-permissions"]
        if mode == "plan":
            return ["--mode", "plan"]
        return ["--mode", "accept-edits"]
    return []


def model_args(flavor: str, model: str | None) -> list[str]:
    """Translate a picker's model id into the CLI's ``--model`` argument.

    Returns an empty list when the id is a synthetic placeholder (legacy
    registration rows) — the CLI then falls back to its own default. An id starting with
    ``-`` would be read as a flag (``--yolo``): ``ValueError``.
    """
    if not model:
        return []
    stripped = model.strip()
    if not stripped:
        return []
    if stripped.startswith("-"):
        raise ValueError(f"a model id cannot start with '-': {stripped[:40]!r}")
    if stripped.lower() in {
        "default",
        "claude code",
        "cursor agent",
        "google antigravity",
        "gemini cli",
    }:
        return []

    if flavor == "grok":
        if stripped.endswith("-high"):
            return ["--model", stripped[:-5], "--reasoning-effort", "high"]
        elif stripped.endswith("-low"):
            return ["--model", stripped[:-4], "--reasoning-effort", "low"]

    return ["--model", stripped]


def compose_prompt(
    flavor: str, latest_user: str, system_text: str, resume_id: str | None
) -> str:
    """Compose the -p prompt; only Claude supports --append-system-prompt.

    Other flavors inline the system text ahead of the user message on the
    first turn; resumed sessions already carry it in the CLI's own history.
    """
    if flavor == "claude" or resume_id or not system_text:
        return latest_user
    return f"{system_text}\n\n{latest_user}"


def _claude_allowed_tools(
    mode: str, allowed_tools: list[str] | None, *, live_input: bool = False,
) -> list[str]:
    """Claude's ``--allowedTools`` argv for a permission mode.

    ``None`` is the default list. A non-live turn keeps ``Bash,Read``, plus ``Edit,Write``
    outside plan/manual. A live turn omits Bash: ``Read``, plus ``Edit,Write`` outside
    plan/manual, and never a ``Bash(d3skwebscout …)`` rule. A list replaces the default,
    comma-joined (a rule cannot contain a comma: ``ValueError``); ``[]`` adds no default
    ``--allowedTools`` at all. ``cli_args`` can still add rules (a repeated flag adds).
    """
    if allowed_tools is None:
        if live_input:
            tools = "Read" if mode in ("plan", "manual") else "Read,Edit,Write"
        else:
            tools = "Bash,Read" if mode in ("plan", "manual") else "Bash,Read,Edit,Write"
        return ["--allowedTools", tools]
    if any("," in rule for rule in allowed_tools):
        raise ValueError(f"an allowed_tools rule cannot contain a comma: {allowed_tools!r}")
    return ["--allowedTools", ",".join(allowed_tools)] if allowed_tools else []


def _rule_path(path: Path) -> str:
    """An absolute path as Claude's permission rules spell it: ``//`` then POSIX form."""
    posix = path.as_posix()
    if len(posix) > 1 and posix[1] == ":":  # C:/Users → /c/Users
        posix = f"/{posix[0].lower()}{posix[2:]}"
    return "/" + posix if posix.startswith("/") else "//" + posix


def token_file_denials(home: Path | None = None) -> list[str]:
    """Claude deny rules that keep the agent off the bridge home and the gateway's token files.

    Defense in depth for a turn that may run Bash: the gateway's tokens sit in the bridge home
    (``gateway_auth``), and a client-token turn must not read the owner token. A deny rule beats
    every allow rule; ``*`` matches anywhere in a Bash rule (checked live 2026-11-02, Claude Code
    2.1.316). A command that builds the path at run time (variables, quoting tricks) gets past
    the Bash rules: the real boundary is that the CLI's directory is outside the bridge home,
    and that the modes running every tool unasked are owner-only at the gateway.
    """
    from .gateway_auth import OWNER_TOKEN_FILE, TOKEN_FILE, bridge_home_path

    home = (home or bridge_home_path()).expanduser()
    spellings = {home.as_posix(), str(home)}
    if home.is_relative_to(Path.home()):
        relative = home.relative_to(Path.home()).as_posix()
        spellings |= {f"~/{relative}", f"$HOME/{relative}", f"${{HOME}}/{relative}"}
    rules = [f"{tool}({_rule_path(home)}/**)" for tool in ("Read", "Edit", "Write")]
    for name in (TOKEN_FILE, OWNER_TOKEN_FILE):
        rules += [f"Read(**/{name})", f"Bash(*{name}*)"]
    for spelling in sorted(spellings):
        rules += [f"Bash(*{spelling})", f"Bash(*{spelling}/*)", f"Bash(*{spelling} *)"]
    if "agent-cli-bridge" in home.name.lower():  # "$HOME"/.agent-cli-bridge/…: a name no other folder has
        rules += [f"Bash(*{home.name}/*)", f"Bash(*/{home.name})", f"Bash(*/{home.name} *)"]
    return [rule for rule in rules if "," not in rule]


def build_argv(
    *,
    binary: str,
    flavor: str,
    prompt: str,
    system_text: str = "",
    resume_id: str | None = None,
    cli_args: list[str] | None = None,
    model: str | None = None,
    permission_mode: str | None = None,
    live_input: bool = False,
    cwd: str | None = None,
    prompt_on_stdin: bool = False,
    allowed_tools: list[str] | None = None,
) -> list[str]:
    """Build the headless argv for a CLI agent flavor.

    ``live_input`` (Claude only, see control.py): the prompt is not in argv but written
    to stdin as stream-json, which then also carries tool approvals and extra messages.
    ``cwd`` is the process working directory; it is repeated as an explicit flag for CLIs that
    do not trust it — Antigravity needs ``--add-dir`` because ``agy -p`` does not treat the
    subprocess cwd as the workspace.
    ``prompt_on_stdin`` (``STDIN_PROMPT_FLAVORS`` only): the argv asks the CLI to read its prompt
    from stdin, for a prompt too long for the command line (``windows_launch.is_too_long``).
    ``allowed_tools`` (Claude only, others ignore it) replaces its default ``--allowedTools``
    list: see ``_claude_allowed_tools``.
    """
    cli_args = list(cli_args or [])
    m_args = model_args(flavor, model)
    perm_args = permission_args(flavor, permission_mode)
    mode = normalize_permission_mode(permission_mode)

    if flavor == "cursor":
        # Cursor Agent CLI: -p/--print + stream-json (+ partial deltas).
        # https://cursor.com/docs/cli/headless
        argv = [
            binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--stream-partial-output",
        ]
        argv += m_args
        if resume_id:
            argv += ["--resume", resume_id]
        argv += perm_args
        argv += cli_args
        return argv

    if flavor == "antigravity":
        # Google Antigravity CLI (`agy`): non-interactive -p prints stream-json.
        # `agy -p` ignores process cwd and starts in default-cli-project unless
        # --add-dir is set (`agy --help`: "Add a directory to the workspace").
        # --conversation resumes the id the stream's init event carried (verified
        # live 2026-09-25, agy 1.2.11): without it every turn was a fresh session, and
        # compose_prompt had already dropped the system text for a resumed turn.
        argv = [binary, "-p", prompt, "--output-format", "stream-json"]
        argv += m_args
        if resume_id:
            argv += ["--conversation", resume_id]
        argv += perm_args
        if cwd:
            argv += ["--add-dir", cwd]
        argv += cli_args
        return argv

    if flavor == "grok":
        # Without --include-partial-messages Grok prints whole messages only, so no
        # text reaches the host until the turn ends. With it, the stream matches
        # Claude Code's stream_event deltas (verified live 2026-09-13).
        argv = [
            binary,
            "-p",
            "-" if prompt_on_stdin else prompt,  # `grok -p -` reads stdin (verified 2026-10-12, 1.0.52)
            "--output-format",
            "streaming-messages-json",
            "--include-partial-messages",
        ]
        argv += m_args
        if resume_id:
            argv += ["--resume", resume_id]
        argv += perm_args
        argv += cli_args
        return argv

    if flavor == "opencode":
        # OpenCode: `run --format json` prints one JSON event per finished part
        # (text, reasoning, tool_use, error). --thinking adds the reasoning parts.
        # The project is the process cwd. OpenCode 1.x took it as `--dir`; OpenCode
        # 2.0 rejects that flag (`Unrecognized flag: --dir in command opencode run`,
        # verified live 2026-10-04 on 2.0.20). Its positional directory is the TUI's
        # (`opencode <directory>`), not `run`'s. The runner also sets PWD to the
        # same path, which is what OpenCode 1 preferred over the process cwd.
        # `--` keeps a prompt starting with "-" from being read as a flag.
        argv = [binary, "run", "--format", "json", "--thinking"]
        argv += m_args
        if resume_id:
            argv += ["--session", resume_id]
        argv += perm_args
        argv += cli_args
        argv += ["--", prompt]
        return argv

    if flavor == "gemini":
        # Gemini CLI headless: -p + stream-json for line-by-line streaming.
        # --skip-trust avoids the interactive workspace-trust prompt.
        # --approval-mode sets read-only vs auto-approve. docs/cli/headless.md.
        argv = [binary, "-p", prompt, "--output-format", "stream-json", "--skip-trust"]
        argv += m_args
        argv += perm_args
        argv += cli_args
        return argv

    if flavor == "copilot":
        # GitHub Copilot CLI: -p + JSONL events (copilot --help). --no-ask-user
        # because a headless host can't answer the ask_user tool; logging and
        # auto-update off to keep stdout pure JSONL.
        argv = [
            binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--no-color",
            "--no-auto-update",
            "--log-level",
            "none",
            "--no-ask-user",
        ]
        argv += m_args
        if resume_id:
            argv += [f"--resume={resume_id}"]
        argv += perm_args
        argv += cli_args
        return argv

    # Default: Claude Code protocol.
    if live_input:
        argv = [
            binary,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--replay-user-messages",
            "--permission-prompt-tool",
            "stdio",
        ]
    else:
        argv = [binary, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
    argv += m_args
    if resume_id:
        argv += ["--resume", resume_id]
    if system_text:
        argv += ["--append-system-prompt", system_text]
    argv += perm_args
    # Non-live turns allow Bash so a host that cannot answer an approval can still run helper
    # scripts; a live turn omits it (live_approvals.py). The token files stay denied on both.
    argv += _claude_allowed_tools(mode, allowed_tools, live_input=live_input)
    argv += ["--disallowedTools", ",".join(token_file_denials())]
    argv += cli_args
    if not live_input and not prompt_on_stdin:
        # Last, after `--`, so a prompt starting with "-" (a page's text) is never read as a
        # flag. `claude -p` with no prompt reads it from stdin (verified 2026-10-27, 2.1.311).
        argv += ["--", prompt]
    return argv


def _settings_object(value: str) -> dict[str, Any] | None:
    """A ``--settings`` value as a dict: inline JSON, or the JSON file it names."""
    text = value.strip()
    if not text.startswith("{"):
        try:
            text = Path(text).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("--settings %r cannot be read: %s", value, exc)
            return None
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        log.warning("--settings %r is not JSON: %s", value[:80], exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def _merge_settings(into: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if key == "permissions" and isinstance(value, dict) and isinstance(into.get(key), dict):
            merged = dict(into[key])
            for rule_key, rules in value.items():
                if isinstance(rules, list) and isinstance(merged.get(rule_key), list):
                    merged[rule_key] = [*merged[rule_key], *(r for r in rules if r not in merged[rule_key])]
                else:
                    merged[rule_key] = rules
            into[key] = merged
        else:
            into[key] = value


def merge_settings_args(args: list[str]) -> list[str]:
    """Claude Code keeps only the LAST ``--settings`` (checked live, 2.1.x): fold every
    ``--settings`` in ``args`` into one, in order (later keys win, ``permissions`` rule lists
    are concatenated), appended at the end. Unreadable values are dropped with a warning."""
    rest: list[str] = []
    values: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--settings" and index + 1 < len(args):
            values.append(args[index + 1])
            index += 2
            continue
        if arg.startswith("--settings="):
            values.append(arg.split("=", 1)[1])
        else:
            rest.append(arg)
        index += 1
    if len(values) < 2:
        return list(args)
    merged: dict[str, Any] = {}
    for value in values:
        parsed = _settings_object(value)
        if parsed is not None:
            _merge_settings(merged, parsed)
    return [*rest, "--settings", json.dumps(merged, separators=(",", ":"))]
