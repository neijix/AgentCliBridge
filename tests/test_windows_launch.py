"""Windows .cmd launchers: a turn runs the program behind them, never cmd.exe.

The launcher texts are the real ones installed on 2026-10-09 (npm cmd-shim for Gemini, Grok and
OpenCode; Cursor Agent's agent.cmd + cursor-agent.ps1), trimmed to the lines that matter.
"""
import asyncio
import json
import sys

import pytest

from agent_cli_bridge import run_agent, runner
from agent_cli_bridge.control import TurnInput
from agent_cli_bridge.events import StreamError, TextDelta
from agent_cli_bridge.windows_launch import UnsafeLauncherError, direct_launch, is_too_long, npm_shim_argv

NPM_NODE_SHIM = r"""@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\node.exe" (
  SET "_prog=%dp0%\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\node_modules\@google\gemini-cli\bundle\gemini.js" %*
"""

NPM_EXE_SHIM = r"""@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
"%dp0%\node_modules\opencode-ai\bin\opencode.exe"   %*
"""

CURSOR_CMD = r"""@echo off
setlocal enabledelayedexpansion
set "CURSOR_INVOKED_AS=%~nx0"
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\cursor-agent.ps1" %*
"""

PROMPT = 'Say "hi" & then | type <this> ^ 100% done!\nSecond line'


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_an_npm_node_shim_runs_its_script_with_the_node_beside_it(tmp_path):
    (tmp_path / "gemini.cmd").write_text(NPM_NODE_SHIM)
    node = _touch(tmp_path / "node.exe")
    script = _touch(tmp_path / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    argv, env = direct_launch([str(tmp_path / "gemini.cmd"), "-p", PROMPT], is_windows=True)
    assert argv == [str(node), str(script), "-p", PROMPT]
    assert env == {}


def test_an_npm_node_shim_without_a_local_node_uses_node_from_path_by_full_path(tmp_path):
    shim = tmp_path / "npm"
    _touch(shim / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    node = str(_touch(tmp_path / "nodejs" / "node.exe"))  # a real file: the shim's target must exist
    found = npm_shim_argv(NPM_NODE_SHIM, shim, which=lambda name: node)
    assert found is not None and found[0] == node
    assert npm_shim_argv(NPM_NODE_SHIM, shim, which=lambda name: None) is None


def test_an_npm_exe_shim_runs_the_exe(tmp_path):
    (tmp_path / "opencode.cmd").write_text(NPM_EXE_SHIM)
    exe = _touch(tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe")
    argv, _ = direct_launch([str(tmp_path / "opencode.cmd"), "run", PROMPT], is_windows=True)
    assert argv == [str(exe), "run", PROMPT]


def test_a_one_line_launcher_runs_its_program(tmp_path):
    python = _touch(tmp_path / "python.exe")
    (tmp_path / "fake.cmd").write_text(f'@"{python}" "%~dp0fake.py" %*\n')
    argv, _ = direct_launch([str(tmp_path / "fake.cmd"), PROMPT], is_windows=True)
    assert argv == [str(python), str(tmp_path / "fake.py"), PROMPT]


def test_cursor_agent_runs_the_newest_versions_node_and_index(tmp_path):
    (tmp_path / "agent.cmd").write_text(CURSOR_CMD)
    _touch(tmp_path / "cursor-agent.ps1")
    for version in ("2026.9.30-aaaa111", "2026.10.01-e373342", "2026.10.01-14-05-09-bbbb222"):
        _touch(tmp_path / "versions" / version / "node.exe")
        _touch(tmp_path / "versions" / version / "index.js")
    _touch(tmp_path / "versions" / "not-a-version" / "node.exe")
    newest = tmp_path / "versions" / "2026.10.01-14-05-09-bbbb222"
    argv, env = direct_launch([str(tmp_path / "agent.cmd"), "-p", PROMPT], is_windows=True)
    assert argv == [str(newest / "node.exe"), str(newest / "index.js"), "-p", PROMPT]
    assert env["CURSOR_INVOKED_AS"] == "agent.cmd"


def test_an_unreadable_launcher_runs_only_with_arguments_cmd_leaves_alone(tmp_path):
    launcher = tmp_path / "odd.cmd"
    launcher.write_text("@echo off\r\ncall %ODD_HOME%\\odd.exe %*\r\n")
    assert direct_launch([str(launcher), "--version"], is_windows=True) == ([str(launcher), "--version"], {})
    for unsafe in ('say "hi"', "a & calc", "50%", "two\nlines"):
        with pytest.raises(UnsafeLauncherError):
            direct_launch([str(launcher), "-p", unsafe], is_windows=True)


def test_nothing_changes_off_windows_or_for_a_real_executable(tmp_path):
    (tmp_path / "gemini.cmd").write_text(NPM_NODE_SHIM)
    argv = [str(tmp_path / "gemini.cmd"), "-p", PROMPT]
    assert direct_launch(argv, is_windows=False) == (argv, {})
    claude = [r"C:\Users\me\.local\bin\claude.exe", "-p", PROMPT]
    assert direct_launch(claude, is_windows=True) == (claude, {})


def test_a_launcher_that_runs_a_launcher_is_seen_through_or_refused(tmp_path):
    # Review of 2026-10-09: `@"%~dp0inner.bat" %*` ran an injected `&echo` through cmd.exe.
    python = _touch(tmp_path / "python.exe")
    (tmp_path / "inner.bat").write_text(f'@"{python}" "%~dp0tool.py" %*\n')
    (tmp_path / "outer.cmd").write_text('@"%~dp0inner.bat" %*\n')
    argv, _ = direct_launch([str(tmp_path / "outer.cmd"), "-p", "a&echo,PWNED"], is_windows=True)
    assert argv == [str(python), str(tmp_path / "tool.py"), "-p", "a&echo,PWNED"]

    (tmp_path / "inner.bat").write_text("@echo off\r\ncall %HOME%\\tool.exe %*\r\n")
    with pytest.raises(UnsafeLauncherError):
        direct_launch([str(tmp_path / "outer.cmd"), "-p", "a&echo,PWNED"], is_windows=True)


def test_a_node_cmd_found_on_path_is_not_trusted_either(tmp_path):
    (tmp_path / "gemini.cmd").write_text(NPM_NODE_SHIM)
    _touch(tmp_path / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    tools = tmp_path / "tools"
    (_touch(tools / "node.cmd")).write_text("@echo off\r\ncall %NODE_HOME%\\node.exe %*\r\n")
    env = {"PATH": str(tools), "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
    with pytest.raises(UnsafeLauncherError):
        direct_launch([str(tmp_path / "gemini.cmd"), "-p", PROMPT], env, is_windows=True)


def test_the_shims_interpreter_is_read_from_the_shim_and_found_on_the_childs_path(tmp_path):
    shim = NPM_NODE_SHIM.replace('SET "_prog=node"', 'SET "_prog=python3"').replace("node.exe", "python3.exe")
    _touch(tmp_path / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js")
    python = str(_touch(tmp_path / "py" / "python3.exe"))
    asked = []
    found = npm_shim_argv(shim, tmp_path, which=lambda name: asked.append(name) or python)
    assert asked == ["python3"] and found is not None and found[0] == python


def test_quoted_tokens_with_other_variables_and_parentheses_are_refused(tmp_path):
    launcher = tmp_path / "odd.cmd"
    launcher.write_text('@"%ODD_HOME%\\odd.exe" %*\n')
    for unsafe in ("x)", "(y"):
        with pytest.raises(UnsafeLauncherError):
            direct_launch([str(launcher), "-p", unsafe], is_windows=True)


@pytest.mark.parametrize("suffix", [".cmd.", ".cmd ", ".BAT"])
def test_a_launcher_name_with_a_trailing_dot_or_space_is_still_a_launcher(tmp_path, suffix):
    launcher = tmp_path / "odd.cmd"
    launcher.write_text("@echo off\r\ncall %ODD_HOME%\\odd.exe %*\r\n")
    with pytest.raises(UnsafeLauncherError):
        direct_launch([str(tmp_path / "odd") + suffix, "-p", "a&b"], is_windows=True)


def test_cursor_agent_env_and_an_incomplete_newest_version(tmp_path):
    (tmp_path / "agent.cmd").write_text(CURSOR_CMD)
    _touch(tmp_path / "cursor-agent.ps1")
    complete = tmp_path / "versions" / "2026.9.30-AAAA111"  # the ps1's -match ignores case
    _touch(complete / "node.exe")
    _touch(complete / "index.js")
    _touch(tmp_path / "versions" / "2026.10.01-e373342" / "node.exe")  # no index.js yet
    env = {"LOCALAPPDATA": r"C:\Users\me\AppData\Local", "CURSOR_INVOKED_AS": "host-value"}
    argv, overlay = direct_launch([str(tmp_path / "agent.cmd")], env, is_windows=True)
    assert argv == [str(complete / "node.exe"), str(complete / "index.js")]
    assert overlay["CURSOR_INVOKED_AS"] == "agent.cmd"  # agent.cmd overrides it too
    assert overlay["NODE_COMPILE_CACHE"].endswith("cursor-compile-cache")
    _, overlay = direct_launch([str(tmp_path / "agent.cmd")], {**env, "NODE_COMPILE_CACHE": "x"}, is_windows=True)
    assert "NODE_COMPILE_CACHE" not in overlay


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe launchers exist only on Windows")
def test_a_turn_through_an_unreadable_launcher_is_refused_not_mangled(tmp_path):
    launcher = tmp_path / "odd.cmd"
    launcher.write_text("@echo off\r\ncall %ODD_HOME%\\odd.exe %*\r\n")

    turn_input = TurnInput()

    async def collect():
        return [e async for e in run_agent("claude", prompt=PROMPT, binary=str(launcher), turn_input=turn_input)]

    events = asyncio.run(collect())
    assert isinstance(events[0], StreamError) and events[0].code == "spawn_failed"
    assert "cmd.exe would rewrite" in events[0].message
    assert turn_input.say("more") is False  # closed: nothing waits on a turn that never started


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe launchers exist only on Windows")
def test_a_prompt_reaches_a_launched_program_intact(tmp_path):
    # The program prints its argv as a Gemini-style result: every argument must arrive untouched.
    (tmp_path / "echo_argv.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'type': 'result', 'result': json.dumps(sys.argv[1:])}))\n"
    )
    launcher = tmp_path / "gemini.cmd"
    launcher.write_text(f'@"{sys.executable}" "%~dp0echo_argv.py" %*\n')

    async def collect():
        return [e async for e in run_agent("gemini", prompt=PROMPT, binary=str(launcher))]

    events = asyncio.run(collect())
    received = json.loads("".join(e.text for e in events if isinstance(e, TextDelta)))
    assert any(PROMPT in arg for arg in received)  # the guard's policy may precede it


ECHO_PROMPT = (
    "import json, sys\n"
    "args = sys.argv[1:]\n"
    "prompt = args[args.index('-p') + 1]\n"
    "source = 'argv'\n"
    "if prompt == '-':\n"
    "    prompt, source = sys.stdin.buffer.read().decode('utf-8'), 'stdin'\n"
    "print(json.dumps({'type': 'result', 'result': json.dumps([source, prompt])}))\n"
)


def _echo_cli(tmp_path, name):
    """A fake CLI that answers with where its prompt came from and the prompt itself."""
    (tmp_path / "echo_prompt.py").write_text(ECHO_PROMPT)
    if sys.platform == "win32":
        launcher = tmp_path / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" "%~dp0echo_prompt.py" %*\n')
        return launcher
    launcher = tmp_path / name
    launcher.write_text(f"#!{sys.executable}\n{ECHO_PROMPT}")
    launcher.chmod(0o755)
    return launcher


def _long_command_lines(monkeypatch):
    """Any OS behaves like Windows with a small limit: an argument over 1,000 characters is too long."""
    monkeypatch.setattr(runner, "is_too_long", lambda argv: any(len(arg) > 1000 for arg in argv))
    monkeypatch.setattr(runner, "command_line_length", lambda argv: sum(len(arg) + 1 for arg in argv))


def test_the_windows_command_line_limit():
    assert is_too_long(["grok", "-p", "x" * 40_000], is_windows=True)
    assert not is_too_long(["grok", "-p", "x" * 30_000], is_windows=True)
    assert not is_too_long(["grok", "-p", "x" * 40_000], is_windows=False)  # no such limit elsewhere
    assert is_too_long(["grok", "-p", "😀" * 17_000], is_windows=True)  # Windows counts UTF-16 units


def test_one_argument_too_long_for_linux_is_too_long():
    """Linux refuses one argument of 128 KiB (MAX_ARG_STRLEN), whatever the whole line."""
    assert is_too_long(["claude", "-p", "x" * 131_072], is_windows=False, is_linux=True)
    assert is_too_long(["claude", "-p", "é" * 65_536], is_windows=False, is_linux=True)  # bytes count
    assert not is_too_long(["claude", "-p", "x" * 131_071], is_windows=False, is_linux=True)
    assert not is_too_long(["claude", "-p", "x" * 131_072], is_windows=False, is_linux=False)


def test_windows_too_long_error_is_not_reported_as_a_missing_binary(tmp_path, monkeypatch):
    """CreateProcess's ERROR_FILENAME_EXCED_RANGE (206) reaches Python as FileNotFoundError."""
    async def refuse(*args, **kwargs):
        error = FileNotFoundError(2, "The filename or extension is too long")
        error.winerror = 206
        raise error

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", refuse)

    async def collect():
        return [e async for e in run_agent("gemini", prompt="hi", binary=str(_echo_cli(tmp_path, "gemini")),
                                           web_scout=False)]

    events = asyncio.run(collect())
    assert len(events) == 1 and events[0].code == "prompt_too_long"


def test_grok_reads_a_prompt_too_long_for_its_command_line_from_stdin(tmp_path, monkeypatch):
    """Regression (2026-10-12): a whole transcript handed to Grok on Windows failed with
    WinError 206, reported as "CLI agent binary not found on PATH: grok"."""
    _long_command_lines(monkeypatch)
    prompt = "é" + "x" * 5000

    async def collect():
        return [e async for e in run_agent("grok", prompt=prompt, binary=str(_echo_cli(tmp_path, "grok")),
                                           web_scout=False)]

    events = asyncio.run(collect())
    source, received = json.loads("".join(e.text for e in events if isinstance(e, TextDelta)))
    assert source == "stdin" and received.endswith(prompt)
    short = asyncio.run(_collect_short(tmp_path))
    assert json.loads(short)[0] == "argv"  # a prompt that fits stays where it was


async def _collect_short(tmp_path):
    events = [e async for e in run_agent("grok", prompt="hi", binary=str(_echo_cli(tmp_path, "grok")), web_scout=False)]
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def test_a_cli_that_only_takes_its_prompt_on_the_command_line_says_it_is_too_long(tmp_path, monkeypatch):
    _long_command_lines(monkeypatch)
    turn_input = TurnInput()

    async def collect():
        return [e async for e in run_agent("gemini", prompt="x" * 5000, binary=str(_echo_cli(tmp_path, "gemini")),
                                           web_scout=False, turn_input=turn_input)]

    events = asyncio.run(collect())
    assert len(events) == 1 and events[0].code == "prompt_too_long"
    assert "too long for the Windows command line" in events[0].message
    assert turn_input.say("more") is False
