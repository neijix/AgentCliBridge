"""Spawn a CLI agent and stream its output as structured events.

The transport-agnostic core of the bridge: consumers get TextDelta /
SessionUpdate / StreamError / Completed events (events.py) and never see a transport
frame from here; a host that streams to a web page maps them with ``wire.py``
(the shared SSE format), any other host formats its own. ``activity=True`` adds
ThinkingDelta / ToolCall / ToolResult so a host can show what the agent is doing. Cancellation semantics are strict — closing/cancelling the
generator kills the CLI's whole process group immediately (agents spawn
children that inherit our pipes; killing only the parent leaves orphans
holding stderr open, which blocks cleanup until they exit).
"""
import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any

from .argv import STDIN_PROMPT_FLAVORS, build_argv, compose_prompt, merge_settings_args
from .child_env import child_env
from .claude_account import claude_profile_env
from .control import TurnInput, supports_live_input, user_message
from .events import Completed, StreamError, StreamEvent, ThinkingDelta, ToolCall, ToolResult
from .injection_guard import InjectionGuard
from .live_approvals import guard_turn_events, remember_spawned, turn_process_capture
from .output.antigravity import parse_stdout as parse_antigravity
from .output.claude import parse_stdout as parse_claude
from .output.claude import runs_background_agents as _runs_background_agents  # noqa: F401  tests import this name
from .output.common import SessionIds
from .output.copilot import CopilotStatus
from .output.copilot import parse_stdout as parse_copilot
from .output.cursor import extract_cursor_text as _extract_cursor_text  # noqa: F401  tests import this name
from .output.cursor import parse_stdout as parse_cursor
from .output.gemini import parse_stdout as parse_gemini
from .output.grok import parse_stdout as parse_grok
from .output.opencode import parse_stdout as parse_opencode
from .processes import background_process_options
from .security_log import SecurityLog
from .specs import cli_agent_spec, flavor_for, resolve_binary
from .turn_pipes import stderr_tail, turn_stdin
from .web_scout import WebScout
from .windows_launch import (
    COMMAND_LINE_LIMIT,
    LINUX_ARG_LIMIT,
    UnsafeLauncherError,
    command_line_length,
    direct_launch,
    is_too_long,
)

ACTIVITY_EVENTS = (ThinkingDelta, ToolCall, ToolResult)  # only yielded with activity=True

logger = logging.getLogger(__name__)

# How long a CLI may keep its stdout open once it has reported the end of its turn (a
# `result` event). Past that, the turn ends anyway: a CLI that lingers, or a child it
# started that inherited our pipe (a server, a browser), must not leave the host's turn
# "working" until someone presses Stop.
RESULT_GRACE_SECONDS = 15.0
_EXIT_GRACE_SECONDS = 3.0  # then a CLI still running after its result is killed
_EXIT_POLL_SECONDS = 1.0  # how often a read with no deadline checks whether the CLI exited

_ERROR_FILENAME_EXCED_RANGE = 206  # Windows: a command line over COMMAND_LINE_LIMIT


def _too_long_message(command: str, argv: list[str]) -> str:
    length = command_line_length(argv)
    if not length:  # not Windows: Linux's limit on one argument
        return (
            f"This turn is too long for the command line that starts {command} (one argument "
            f"reaches the {LINUX_ARG_LIMIT:,}-byte limit). Shorten the message, or continue in a new chat."
        )
    return (
        f"This turn is too long for the Windows command line that starts {command} "
        f"({length:,} characters; the limit is {COMMAND_LINE_LIMIT:,}). "
        "Shorten the message, or continue in a new chat."
    )


def spawn_options(os_name: str | None = None) -> dict[str, Any]:
    """Platform keywords for spawning a CLI agent.

    POSIX: its own session (process group) so cancellation can kill the whole
    tree — see module docstring. Windows: no console window.
    """
    name = os_name or os.name
    if name == "nt":
        return background_process_options(name)
    return {"start_new_session": name == "posix"}


class _Seen:
    """Whether this turn already yielded text or an in-band error."""

    def __init__(self) -> None:
        self.yes = False


class _AfterResult:
    """The deadline that starts when a CLI reports the end of its turn.

    Before ``start()`` reads wait as long as the CLI works; after it, they wait at most
    ``grace`` seconds in total, and ``expired`` tells the caller that stdout never closed.
    """

    def __init__(self, grace: float, has_exited: Callable[[], bool] | None = None) -> None:
        self.grace = grace
        self.deadline: float | None = None
        self.expired = False
        self.has_exited = has_exited  # the CLI process itself exited, result or not

    def start(self) -> None:
        if self.deadline is None:
            self.deadline = asyncio.get_running_loop().time() + self.grace

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - asyncio.get_running_loop().time())

    def read_timeout(self) -> float | None:
        """How long one read may wait: the deadline, else a poll for the CLI's own exit."""
        remaining = self.remaining()
        if remaining is None and self.has_exited is not None:
            return _EXIT_POLL_SECONDS
        return remaining


async def _bounded(awaitable: Any, timeout: float | None) -> Any:
    if timeout is None:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout)


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the CLI's whole process group (children that inherited our pipes too).

    Also once the CLI itself exited: a child it left still holds our pipes. ``start_new_session``
    makes the group id the CLI's pid, and Linux does not hand out a pid still used as a group id.
    """
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(proc.pid, 9)
            return
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()


def _close_pipes(proc: asyncio.subprocess.Process) -> None:
    """Stop reading the CLI's pipes, so neither a read nor ``wait()`` waits on a child holding one."""
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        with contextlib.suppress(Exception):
            transport.close()


async def _reap(
    proc: asyncio.subprocess.Process,
    stderr: Any,
    after_result: _AfterResult,
    *,
    interrupted: bool,
    command: str,
) -> tuple[int, bytes]:
    """The CLI's exit code and stderr once its stdout ended, was abandoned or was interrupted.

    The stderr drain is skipped after an interrupt or an expired deadline: a surviving child
    holding the pipe would block it. A CLI still running past its deadline is killed and the turn
    counts as a success, its answer being complete. A child the CLI started on a clean finish is
    left running: it may be what the user asked for.
    """
    stderr_data = b""
    if not interrupted and not after_result.expired:
        with contextlib.suppress(Exception):
            stderr_data = await _bounded(stderr.read(), after_result.remaining())
    if after_result.expired:
        logger.warning("%s left stdout open after its turn ended (a child process holds it); "
                       "ending the turn", command)
    if (interrupted or after_result.expired) and proc.returncode is not None:
        _close_pipes(proc)  # the CLI is gone; wait() would otherwise wait for the child's pipes
    try:
        if after_result.deadline is None and not interrupted:
            return await proc.wait(), stderr_data
        return await _bounded(proc.wait(), _EXIT_GRACE_SECONDS), stderr_data
    except TimeoutError:
        if proc.returncode is None:
            if not interrupted:
                logger.warning("%s still running %.0fs after its result; stopping it", command,
                               RESULT_GRACE_SECONDS + _EXIT_GRACE_SECONDS)
            _kill_tree(proc)
        _close_pipes(proc)
        with contextlib.suppress(Exception):
            await _bounded(proc.wait(), _EXIT_GRACE_SECONDS)
        return 0, stderr_data
    except Exception:
        return (proc.returncode if proc.returncode is not None else -1), stderr_data


async def _iter_lines(reader: asyncio.StreamReader, after_result: _AfterResult | None = None):
    """Yield newline-delimited chunks without asyncio's 64 KiB line ceiling.

    ``async for line in reader`` uses StreamReader.readline(), which raises
    LimitOverrunError/ValueError past the default 64 KiB limit — and Cursor
    Agent's stream-json buffered flushes (whole tool outputs, e.g. batches of
    email bodies) routinely blow past it, crashing the turn. Reading raw
    chunks and splitting ourselves has no per-line ceiling; the CLIs are
    trusted local binaries, so no hard memory cap is enforced.
    """
    buf = bytearray()
    while True:
        timeout = after_result.read_timeout() if after_result is not None else None
        try:
            chunk = await _bounded(reader.read(65536), timeout)
        except TimeoutError:  # only ever raised with an after_result
            if after_result is None:
                return
            if after_result.deadline is None:
                # The poll: a CLI that exited without a result gets the same grace.
                if after_result.has_exited is not None and after_result.has_exited():
                    after_result.start()
                continue
            after_result.expired = True
            if buf:
                yield bytes(buf)
            return
        if not chunk:
            if buf:
                yield bytes(buf)
            return
        buf += chunk
        while True:
            newline = buf.find(b"\n")
            if newline < 0:
                break
            yield bytes(buf[: newline + 1])
            del buf[: newline + 1]


def _unwrap_json_error(raw: str, fallback: str) -> str:
    """Surface the human message from a CLI JSON error object, if present.

    E.g. Gemini's ``--output-format json`` failure payload on stderr:
    ``{session_id, error: {message, code}}``.
    """
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict) and err.get("message"):
                return err["message"]
            if isinstance(err, str) and err:
                return err
    except Exception:
        pass
    return fallback


# OpenCode sets no timeout between streamed chunks by default: an OpenRouter stealth model
# that stopped mid-stream left a turn waiting 29 minutes (2026-09-17). With the provider's
# `chunkTimeout` option, a silent stream is aborted and OpenCode retries it with backoff
# (verified 2026-09-17, OpenCode 1.18.5). OpenRouter sends keep-alive comments while a
# model thinks, and those count as chunks, so only a dead stream trips it.
OPENCODE_CHUNK_TIMEOUT_MS = 120_000


# `claude -p` stops the background subagents still running 10 minutes after its last turn
# ("Background tasks still running … after the last turn; stopping them", claude 2.1.300,
# default 600000). Four code reviews launched in the background were killed mid-work and the
# chat ended on "waiting for the reviews" (2026-10-15). The runner already keeps the turn open
# while an agent works, and Stop ends it; 0 tells Claude to wait for them too.
CLAUDE_BG_WAIT_CEILING_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"


def claude_background_wait(env: dict[str, str]) -> None:
    """Let Claude wait for its background subagents, unless the host chose a ceiling."""
    env.setdefault(CLAUDE_BG_WAIT_CEILING_ENV, "0")


def opencode_directory(env: dict[str, str], cwd: str | None) -> None:
    """Point OpenCode at the project without ``--dir``.

    OpenCode 2.0.20 exits with ``Unrecognized flag: --dir in command opencode run``
    and uses the process cwd. OpenCode 1 resolved the project from ``PWD`` before
    that cwd, so the same path is published there.
    """
    if cwd:
        env["PWD"] = cwd


def opencode_config_content(model: str | None, current: str | None) -> str | None:
    """``OPENCODE_CONFIG_CONTENT`` adding a chunk timeout for the model's provider.

    ``model`` is OpenCode's ``provider/model`` id; ``current`` is the value already in the
    environment, merged rather than replaced. Returns None to leave the environment alone:
    no provider in the id, a value that is not a JSON object, or a chunkTimeout the host
    already chose for that provider.
    """
    provider, slash, _ = (model or "").strip().partition("/")
    if not slash or not provider:
        return None
    try:
        config = json.loads(current) if current else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(config, dict):
        return None
    providers = config.setdefault("provider", {})
    if not isinstance(providers, dict):
        return None
    entry = providers.setdefault(provider, {})
    if not isinstance(entry, dict):
        return None
    options = entry.setdefault("options", {})
    if not isinstance(options, dict) or "chunkTimeout" in options:
        return None
    options["chunkTimeout"] = OPENCODE_CHUNK_TIMEOUT_MS
    return json.dumps(config)


async def _run_turn(
    command: str,
    *,
    prompt: str,
    system_text: str = "",
    model: str | None = None,
    permission_mode: str | None = None,
    resume_id: str | None = None,
    cli_args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    binary: str | None = None,
    activity: bool = False,
    turn_input: TurnInput | None = None,
    allowed_tools: list[str] | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """One CLI turn without the injection guard (see ``run_agent``)."""
    flavor = flavor_for(command)
    is_live = turn_input is not None and supports_live_input(flavor)
    if turn_input is not None and not is_live:
        turn_input._close()  # this CLI cannot take input mid-turn: say/answer return False
    live = turn_input if is_live else None  # the TurnInput when this turn takes live input
    if binary is None:
        binary = resolve_binary(command)
    if not binary:
        if turn_input is not None:
            turn_input._close()
        spec = cli_agent_spec(command)
        hint = (spec.install_hint if spec else "") or f"Install `{command}` and ensure it is on PATH."
        yield StreamError(f"CLI agent binary not found: {command}. {hint}", code="not_found")
        return

    final_prompt = compose_prompt(flavor, prompt, system_text, resume_id)

    def turn_argv(prompt_on_stdin: bool = False) -> list[str]:
        return build_argv(
            binary=binary,
            flavor=flavor,
            prompt=final_prompt,
            system_text=system_text,
            resume_id=resume_id,
            cli_args=list(cli_args or []),
            model=model,
            permission_mode=permission_mode,
            live_input=is_live, cwd=cwd,
            prompt_on_stdin=prompt_on_stdin, allowed_tools=allowed_tools,
        )

    argv = turn_argv()

    spawn_env = dict(env) if env is not None else dict(os.environ)
    if extra_env:
        spawn_env.update(extra_env)
    if flavor == "opencode":
        config_content = opencode_config_content(model, spawn_env.get("OPENCODE_CONFIG_CONTENT"))
        if config_content:
            spawn_env["OPENCODE_CONFIG_CONTENT"] = config_content
        # OpenCode 2 reads the process cwd and rejects `--dir`. OpenCode 1 preferred
        # PWD over that cwd, so publish the project path there too.
        opencode_directory(spawn_env, cwd)
    elif flavor == "claude":
        claude_background_wait(spawn_env)
        # the code root's profile (~/.claude-profiles); a dir this process inherited does not pin it
        spawn_env = claude_profile_env(spawn_env, cwd)
    # A long prompt (a transcript, a long page) can exceed the command line (Windows) or one
    # argument (Linux). A CLI that reads its prompt from stdin gets it there instead.
    can_take_stdin_prompt = not is_live and flavor in STDIN_PROMPT_FLAVORS
    is_prompt_on_stdin = can_take_stdin_prompt and is_too_long(argv)
    if is_prompt_on_stdin:
        argv = turn_argv(prompt_on_stdin=True)
    try:
        # Windows: run what a .cmd launcher runs, so cmd.exe never re-reads the prompt.
        argv, launcher_env = direct_launch(argv, spawn_env)
        if can_take_stdin_prompt and not is_prompt_on_stdin and is_too_long(argv):
            is_prompt_on_stdin = True  # only too long once the launcher's program was added
            argv, launcher_env = direct_launch(turn_argv(prompt_on_stdin=True), spawn_env)
    except UnsafeLauncherError as exc:
        if turn_input is not None:
            turn_input._close()
        logger.warning("refused a turn through %s: %s", argv[0], exc)
        yield StreamError(str(exc), code="spawn_failed")
        return
    if is_too_long(argv):
        if turn_input is not None:
            turn_input._close()
        yield StreamError(_too_long_message(command, argv), code="prompt_too_long")
        return
    spawn_env.update(launcher_env)  # what the launcher itself would have set
    stdin = turn_stdin(is_live or is_prompt_on_stdin)

    try:
        proc = remember_spawned(await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=child_env(spawn_env),
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **spawn_options(),
        ))
    except FileNotFoundError as exc:
        if turn_input is not None:
            turn_input._close()
        if getattr(exc, "winerror", None) == _ERROR_FILENAME_EXCED_RANGE:
            # Windows' own "too long" error, which Python raises as FileNotFoundError.
            yield StreamError(_too_long_message(command, argv), code="prompt_too_long")
        else:
            yield StreamError(f"CLI agent binary not found on PATH: {command}", code="not_found")
        return
    except Exception as exc:
        if turn_input is not None:
            turn_input._close()
        yield StreamError(f"Failed to start {command}: {exc}", code="spawn_failed")
        return
    stdout, stderr = proc.stdout, stderr_tail(proc.stderr)  # both piped above
    assert stdout is not None and stderr is not None

    def write_stdin(payload: dict[str, Any]) -> bool:
        stdin = proc.stdin
        if stdin is None or stdin.is_closing():
            return False
        try:
            stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            return False
        return True

    if is_prompt_on_stdin and proc.stdin is not None:
        # The whole prompt, then end of input: the CLI starts once it has read it.
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, RuntimeError):
            proc.stdin.write(final_prompt.encode("utf-8", "replace"))  # a lone surrogate: "?"
        proc.stdin.close()
    if live is not None:
        # The prompt first, then whatever the host said before the CLI was started.
        write_stdin(user_message(final_prompt))
        live._bind(write_stdin)

    sessions = SessionIds()
    seen = _Seen()
    interrupted = False
    pending_error: str | None = None  # in-band CLI error (process may exit 0)
    result_exit: int | None = None  # authoritative exit for JSONL protocols
    after_result = _AfterResult(RESULT_GRACE_SECONDS, has_exited=lambda: proc.returncode is not None)
    lines = _iter_lines(stdout, after_result)
    try:
        if flavor == "antigravity":
            async for event in parse_antigravity(
                lines, activity=activity, sessions=sessions, seen=seen, after_result=after_result
            ):
                yield event
        elif flavor == "cursor":
            async for event in parse_cursor(
                lines, activity=activity, sessions=sessions, seen=seen, after_result=after_result, stdin=proc.stdin
            ):
                yield event
        elif flavor == "copilot":
            copilot = CopilotStatus()
            async for event in parse_copilot(
                lines, activity=activity, sessions=sessions, seen=seen, after_result=after_result, status=copilot
            ):
                yield event
            pending_error = copilot.pending_error
            result_exit = copilot.result_exit
        elif flavor == "opencode":
            async for event in parse_opencode(lines, activity=activity, sessions=sessions, seen=seen):
                yield event
        else:
            parser = {"gemini": parse_gemini, "grok": parse_grok}.get(flavor, parse_claude)
            async for event in parser(
                lines,
                activity=activity,
                sessions=sessions,
                seen=seen,
                after_result=after_result,
                live=live,
                is_live=is_live,
                stdin=proc.stdin,
                write_stdin=write_stdin,
            ):
                yield event
    except BaseException:
        # Consumer stopped/cancelled the stream or a mid-stream failure hit.
        # Kill the whole process group so Stop actually stops the agent —
        # children would otherwise survive and hold our pipes open.
        interrupted = True
        _kill_tree(proc)
        raise
    finally:
        if turn_input is not None:
            turn_input._close()
        returncode, stderr_data = await _reap(
            proc, stderr, after_result, interrupted=interrupted, command=command
        )

    # Only reached on the non-interrupted path (interrupts re-raise above).
    if returncode != 0 and not seen.yes:
        err_raw = stderr_data.decode("utf-8", errors="replace").strip()
        fallback = err_raw or f"{command} exited with status {returncode}"
        yield StreamError(_unwrap_json_error(err_raw, fallback))
    elif pending_error and not seen.yes:
        # In-band failure (e.g. Copilot's session.error while the process
        # itself exits 0).
        yield StreamError(pending_error)
    elif not seen.yes:
        # Process exited cleanly (rc == 0) but wrote no text to stdout — the
        # symptom the user sees as "produced no output". Antigravity in
        # particular does this when a turn is refused, rate-limited, or hits
        # an auth issue: stderr has the reason, stdout stays empty. Surface
        # whatever stderr carries so the client shows something the user can
        # act on instead of a bare empty stream.
        err_raw = stderr_data.decode("utf-8", errors="replace").strip()
        if err_raw:
            yield StreamError(_unwrap_json_error(err_raw, err_raw))
        else:
            yield StreamError(
                f"{command} exited cleanly with no output — the CLI produced "
                "nothing on stdout or stderr. Try again; if it repeats, "
                "run the CLI in a terminal to see what it needs "
                "(auth, quota, or a config prompt).",
                code="empty_output",
            )
    effective_rc = result_exit if result_exit is not None else returncode
    yield Completed(effective_rc if effective_rc is not None else -1)


def _with_scout_env(
    scout: WebScout, flavor: str, env: dict[str, str] | None, extra_env: dict[str, str] | None
) -> dict[str, str] | None:
    """``extra_env`` plus what the scout needs; the host's keys win, except PATH, which is the
    host's (or the base env's) PATH with the scout's shim folder first."""
    base = {**(os.environ if env is None else env), **(extra_env or {})}
    overlay = scout.env(flavor, base)
    if not overlay:
        return extra_env
    merged = {**overlay, **(extra_env or {})}
    for key, value in overlay.items():
        if key.upper() == "PATH":
            if os.name == "nt":  # one PATH whatever its case (``Path`` from the host)
                for host_key in [k for k in merged if k.upper() == "PATH" and k != key]:
                    del merged[host_key]
            merged[key] = value
    return merged


async def run_agent(
    command: str,
    *,
    prompt: str,
    system_text: str = "",
    model: str | None = None,
    permission_mode: str | None = None,
    resume_id: str | None = None,
    cli_args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    binary: str | None = None,
    activity: bool = False,
    turn_input: TurnInput | None = None,
    guard: InjectionGuard | bool = True,
    web_scout: WebScout | bool = True,
    security_log: SecurityLog | bool = True,
    allowed_tools: list[str] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Run one headless CLI-agent turn, yielding structured stream events.

    - ``command`` — spec command or alias ("claude", "agent", "gemini", …).
    - ``prompt`` — the latest user message (see ``compose_prompt`` if you need
      system-text inlining; passing ``system_text`` here handles it).
    - ``env`` — full replacement environment (hosts that need to *remove*
      variables build the dict themselves); defaults to os.environ.
    - ``extra_env`` — overlay merged on top of the base env; hosts inject
      their own trust channel here (the bridge hardcodes nothing
      app-specific).
    - ``binary`` — explicit binary path; resolved via specs when omitted.
    - ``activity`` — also yield ThinkingDelta, ToolCall and ToolResult (off by
      default so consumers written for the four original events see nothing new).
    - ``turn_input`` — lets the host answer tool approvals and add messages while the
      turn runs (Claude only; control.py). Yields ApprovalRequest, InputAccepted and
      ModeChanged.
    - ``guard`` — prompt-injection defense (injection_guard.py), on by default: appends
      the policy, scans tool output and denies non-read-only approvals once tainted. A
      non-live turn's first high-severity finding kills the CLI process group before the
      error event is yielded. Pass an ``InjectionGuard`` to configure it, False to disable.
    - ``web_scout`` — web through D3SKWEBSCOUT only (web_scout.py), on by default for Claude
      Code: its built-in WebSearch/WebFetch are denied, the scout's ``d3skwebscout`` shell
      command is put on the CLI's PATH (merged into ``extra_env``: the scout's PATH entry goes
      first on the base/host PATH, the host's other keys win) and a briefing line is added.
      While a live turn is clean the runner allows generic Bash, one plain search, one plain
      status and one plain fetch, and yields a path, a chain, ``--allow-risky`` and the rest.
      Pass a ``WebScout`` for the checkout, caller, mode and budget; False disables it.
    - ``allowed_tools`` — Claude Code only: ``--allowedTools`` rules replacing the default list
      (``[]`` = none, no commas in a rule). A live turn asks before the scout's commands run.
    - ``security_log`` — every security stop (injection detected, action blocked, page
      withheld by the scout) is appended to the shared log (security_log.py), on by default.
      Pass a ``SecurityLog`` to set its file or source name, False to write nothing.

    Yields TextDelta chunks, SessionUpdate when the CLI's session id is known
    (persist it and pass back as ``resume_id`` next turn), StreamError on
    failure with no output, then Completed. Cancelling/closing the generator
    kills the CLI's process group.
    """
    guard_ = InjectionGuard() if guard is True else (guard or None)
    scout = WebScout() if web_scout is True else (web_scout or None)
    log_ = SecurityLog() if security_log is True else (security_log or None)
    recorder = log_.turn(command=command, model=model, cwd=cwd) if log_ is not None else None
    flavor = flavor_for(command)
    is_live = turn_input is not None and supports_live_input(flavor)
    if scout is not None and scout.is_enforced(flavor):
        cli_args = merge_settings_args([*(cli_args or []), *scout.cli_args(
            flavor, is_live=is_live, allow_scout_commands=not is_live or allowed_tools is not None)])
        system_text = scout.system_text(flavor, system_text)
        extra_env = _with_scout_env(scout, flavor, env, extra_env)
    else:
        scout = None
    with turn_process_capture():
        turn = _run_turn(
            command,
            prompt=prompt,
            system_text=guard_.system_text(system_text) if guard_ else system_text,
            model=model, permission_mode=permission_mode,
            resume_id=resume_id, cli_args=cli_args,
            cwd=cwd, env=env, extra_env=extra_env, binary=binary,
            # the guard and the security log need the tool events
            activity=activity or guard_ is not None or recorder is not None,
            turn_input=turn_input,
            allowed_tools=allowed_tools,
        )
        async with contextlib.aclosing(turn):
            async for event in guard_turn_events(
                turn,
                turn_input=turn_input,
                guard=guard_,
                scout=scout,
                recorder=recorder,
                activity=activity,
                is_live=is_live,
                kill=_kill_tree,
                activity_events=ACTIVITY_EVENTS,
            ):
                yield event
