"""Cancelling the stream must kill the CLI's whole process tree, fast.

The sh → sleep parent/child shape matters: real CLI agents spawn children
that inherit our pipes, so cancellation must kill the whole process group or
cleanup blocks on stderr until the orphan exits (30s here — the elapsed-time
assertion turns that regression into a failure instead of a slow pass).
"""
import asyncio
import contextlib
import os
import sys
import time

import pytest

from agent_cli_bridge import run_agent, runner
from agent_cli_bridge.events import Completed, TextDelta

RESULT = '{"type":"result","subtype":"success","result":"done","session_id":"s1"}'


def test_cancel_kills_process_group(tmp_path):
    script = tmp_path / "slow-cli"
    script.write_text("#!/bin/sh\nsleep 30\n")
    script.chmod(0o755)

    pid_holder = {}
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*argv, **kwargs):
        proc = await real_exec(*argv, **kwargs)
        pid_holder["pid"] = proc.pid
        return proc

    async def scenario():
        asyncio.create_subprocess_exec = spy_exec  # noqa: restore in finally
        try:
            agen = run_agent("claude", prompt="hi", binary=str(script))
            pending = asyncio.ensure_future(agen.__anext__())
            for _ in range(50):
                if "pid" in pid_holder:
                    break
                await asyncio.sleep(0.1)
            assert "pid" in pid_holder, "CLI subprocess never spawned"
            await asyncio.sleep(0.2)
            # Simulate the host's Stop: cancel the consuming task.
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
            with contextlib.suppress(Exception):
                await agen.aclose()
        finally:
            asyncio.create_subprocess_exec = real_exec

    started = time.monotonic()
    asyncio.run(scenario())
    elapsed = time.monotonic() - started
    assert elapsed < 10.0, f"cleanup blocked for {elapsed:.1f}s (orphaned child?)"

    pid = pid_holder["pid"]
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return  # dead — cancel actually stopped the agent
        time.sleep(0.05)
    raise AssertionError(f"CLI subprocess {pid} still alive after cancel")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group kill; the Windows branch stays proc.kill()")
def test_cancel_kills_a_grandchild_in_the_process_group(tmp_path):
    """Killing the turn must kill a grandchild, not only the direct child.

    The shell is SIGKILLed, so it never reaps or signals the sleep it started.
    That grandchild shares the CLI's process group and dies only when the kill
    hits the whole group. ``proc.kill()`` alone leaves it running.
    """
    script = tmp_path / "slow-cli"
    script.write_text("#!/bin/sh\nsleep 60 &\necho $! > grandchild.pid\nwait\n")
    script.chmod(0o755)
    grandchild_file = tmp_path / "grandchild.pid"

    pid_holder: dict[str, int] = {}
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*argv, **kwargs):
        proc = await real_exec(*argv, **kwargs)
        pid_holder["pid"] = proc.pid
        return proc

    async def scenario():
        asyncio.create_subprocess_exec = spy_exec
        agen = run_agent("claude", prompt="hi", binary=str(script), cwd=str(tmp_path))
        pending = asyncio.ensure_future(agen.__anext__())
        try:
            child = None
            for _ in range(50):
                text = grandchild_file.read_text().strip() if grandchild_file.exists() else ""
                if text and "pid" in pid_holder:
                    child = int(text)
                    if _alive(child):
                        break
                await asyncio.sleep(0.1)
            assert "pid" in pid_holder, "CLI subprocess never spawned"
            assert child is not None and _alive(child), "grandchild never started"
            cli = pid_holder["pid"]
            assert os.getpgid(child) == os.getpgid(cli)
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
            return cli, child
        finally:
            asyncio.create_subprocess_exec = real_exec
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending
            with contextlib.suppress(Exception):
                await agen.aclose()

    cli = child = None
    try:
        cli, child = asyncio.run(asyncio.wait_for(scenario(), 15))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and (_alive(cli) or _alive(child)):
            time.sleep(0.05)
        assert not _alive(cli), f"CLI subprocess {cli} still alive after cancel"
        assert not _alive(child), f"grandchild {child} still alive; only the direct child was killed"
    finally:
        for pid in (child, cli):
            if pid is not None and _alive(pid):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, 9)


def test_missing_binary_yields_error_event(tmp_path):
    async def scenario():
        events = []
        async for ev in run_agent(
            "definitely-not-a-real-cli", prompt="hi", binary=None
        ):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert len(events) == 1
    assert events[0].code == "not_found"


def test_giant_single_line_does_not_crash(tmp_path):
    """Lines beyond asyncio's 64 KiB StreamReader limit must stream fine.

    Regression: Cursor Agent's stream-json buffered flushes (whole tool
    outputs — e.g. batches of email bodies) exceeded readline()'s default
    limit and the turn died with 'Separator is not found, and chunk exceed
    the limit' (rendered as Error 500 in the host app).
    """
    payload = "x" * 300_000  # ~5x the 64 KiB ceiling
    script = tmp_path / "fat-cli"
    script.write_text(f'#!/bin/sh\nprintf \'{payload}\\n\'\n')
    script.chmod(0o755)

    async def scenario():
        events = []
        async for ev in run_agent("agy", prompt="hi", binary=str(script)):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    text = "".join(e.text for e in events if hasattr(e, "text"))
    assert len(text.strip()) == 300_000
    assert events[-1].__class__.__name__ == "Completed"
    assert events[-1].returncode == 0


def test_happy_path_plain_text(tmp_path):
    """An antigravity-flavored fake CLI streams plain text to completion."""
    script = tmp_path / "fake-agy"
    script.write_text('#!/bin/sh\nprintf "hello "\nprintf "world\\n"\n')
    script.chmod(0o755)

    async def scenario():
        events = []
        async for ev in run_agent("agy", prompt="hi", binary=str(script)):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    text = "".join(e.text for e in events if hasattr(e, "text"))
    assert "hello world" in text
    assert events[-1].__class__.__name__ == "Completed"
    assert events[-1].returncode == 0


def test_windows_spawn_hides_the_console(monkeypatch):
    """A windowless host must not pop a console for the CLI and each of its children.

    The flag is the shared helper. POSIX still starts a process group, and Windows still
    kills with ``proc.kill()``.
    """
    import inspect
    import subprocess
    from pathlib import Path

    from agent_cli_bridge import processes
    from agent_cli_bridge.runner import spawn_options

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert spawn_options("nt") == {"creationflags": 0x08000000}
    assert spawn_options("nt") == processes.background_process_options("nt")
    assert spawn_options("posix") == {"start_new_session": True}
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "background_process_options" in source
    assert "0x08000000" not in source
    assert "_CREATE_NO_WINDOW" not in source
    kill = inspect.getsource(runner._kill_tree)
    assert 'sys.platform != "win32"' in kill
    assert "os.killpg(proc.pid, 9)" in kill
    assert "proc.kill()" in kill


def _run_fake(tmp_path, body, command="grok"):
    script = tmp_path / "fake-cli"
    script.write_text(f"#!/bin/sh\n{body}")
    script.chmod(0o755)

    async def scenario():
        return [ev async for ev in run_agent(command, prompt="hi", binary=str(script))]

    started = time.monotonic()
    events = asyncio.run(asyncio.wait_for(scenario(), 20))
    return events, time.monotonic() - started


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_child_holding_stdout_after_the_result_does_not_hang_the_turn(tmp_path, monkeypatch):
    """The CLI answered and exited, but a server it started still holds our stdout.

    Regression: the turn waited for stdout EOF forever, so the host showed it working
    until Stop. The child is left running: it may be what the user asked for.
    """
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.5)
    pid_file = tmp_path / "child.pid"
    events, elapsed = _run_fake(
        tmp_path, f"printf '%s\\n' '{RESULT}'\nsleep 30 &\necho $! > {pid_file}\n"
    )
    assert elapsed < 8, f"the turn waited {elapsed:.1f}s for the child"
    assert TextDelta("done") in events
    assert events[-1] == Completed(0)
    child = int(pid_file.read_text())
    try:
        assert _alive(child), "a child the CLI started must not be killed on a clean finish"
    finally:
        os.kill(child, 9)


def test_a_cli_that_never_exits_after_its_result_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_EXIT_GRACE_SECONDS", 0.5)
    pid_file = tmp_path / "cli.pid"
    events, elapsed = _run_fake(tmp_path, f"echo $$ > {pid_file}\nprintf '%s\\n' '{RESULT}'\nexec sleep 30\n")
    assert elapsed < 8, f"the turn waited {elapsed:.1f}s for a CLI that was done"
    assert events[-1] == Completed(0)
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid), "the lingering CLI was left running"


def test_background_subagents_keep_claude_running_after_its_result(tmp_path, monkeypatch):
    """Claude ends its turn "waiting" while background subagents work, then answers again.

    Regression: the deadline started at that first result killed Claude and its
    subagents 18 s later. Event shapes captured live from claude 2.1.296.
    """
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.3)
    monkeypatch.setattr(runner, "_EXIT_GRACE_SECONDS", 0.3)
    tasks = '{"type":"system","subtype":"background_tasks_changed","tasks":[%s]}'
    agent = '{"task_id":"a1","task_type":"local_agent"}'
    bash = '{"task_id":"b1","task_type":"local_bash"}'
    later = '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":" all done"}}}'
    lines = [
        tasks % agent, RESULT, "SLEEP", tasks % f"{agent},{bash}", tasks % bash, later, RESULT,
    ]
    body = "".join("sleep 1\n" if line == "SLEEP" else f"printf '%s\\n' '{line}'\n" for line in lines)
    events, _ = _run_fake(tmp_path, body, command="claude")
    assert events[-3:] == [TextDelta("done"), TextDelta(" all done"), Completed(0)]


def test_a_background_shell_command_does_not_hold_claude_after_its_result():
    """Claude does not wait for a background shell command, so neither does the turn."""
    assert not runner._runs_background_agents({"tasks": [{"task_id": "b1", "task_type": "local_bash"}]})
    assert not runner._runs_background_agents({"tasks": []})
    assert runner._runs_background_agents({"tasks": [{"task_id": "a1", "task_type": "local_agent"}]})


def test_no_deadline_before_the_result(tmp_path, monkeypatch):
    """A CLI working longer than the grace, before its result, is never cut."""
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.2)
    events, _ = _run_fake(tmp_path, f"sleep 1\nprintf '%s\\n' '{RESULT}'\n")
    assert events[-2:] == [TextDelta("done"), Completed(0)]


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX shell fake")
def test_a_cli_that_exits_without_a_result_while_a_child_holds_stdout_ends_the_turn(tmp_path, monkeypatch):
    """No result ever came, so no deadline started: the CLI's own exit starts it."""
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.5)
    monkeypatch.setattr(runner, "_EXIT_POLL_SECONDS", 0.2)
    pid_file = tmp_path / "child.pid"
    later = '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"partial"}}}'
    events, elapsed = _run_fake(
        tmp_path, f"printf '%s\\n' '{later}'\nsleep 30 &\necho $! > {pid_file}\nexit 3\n", command="claude",
    )
    child = int(pid_file.read_text())
    try:
        assert elapsed < 8, f"the turn waited {elapsed:.1f}s for the child"
        assert TextDelta("partial") in events
        assert events[-1] == Completed(3)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child, 9)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group kill")
def test_stop_kills_a_child_the_cli_left_behind_once_it_exited(tmp_path):
    """The CLI already exited; its child still writes to our stdout. Stop must kill that child."""
    script = tmp_path / "exited-cli"
    pid_file = tmp_path / "child.pid"
    later = '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"tick"}}}'
    script.write_text(
        f"#!/bin/sh\n(while true; do printf '%s\\n' '{later}'; sleep 0.1; done) &\n"
        f"echo $! > {pid_file}\nexit 0\n"
    )
    script.chmod(0o755)

    async def scenario():
        agen = run_agent("claude", prompt="hi", binary=str(script))
        async for event in agen:
            if event == TextDelta("tick") and pid_file.exists():
                await asyncio.sleep(0.3)  # the CLI has exited by now
                break
        await agen.aclose()

    started = time.monotonic()
    asyncio.run(asyncio.wait_for(scenario(), 15))
    assert time.monotonic() - started < 8
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert not _alive(child), "Stop left the CLI's child running"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child, 9)


def test_claude_waits_for_its_background_subagents_past_ten_minutes(tmp_path, monkeypatch):
    """`claude -p` killed background subagents 10 minutes after its last turn.

    Regression (claude 2.1.300): four background code reviews were stopped mid-work and
    the chat ended on "waiting for the reviews". The CLI gets a ceiling of 0 (wait for them).
    A Python fake, so it runs on Windows too.
    """
    monkeypatch.delenv(runner.CLAUDE_BG_WAIT_CEILING_ENV, raising=False)
    fake = tmp_path / "fake_claude.py"
    fake.write_text(
        "import json, os\n"
        f"value = os.environ.get({runner.CLAUDE_BG_WAIT_CEILING_ENV!r}, 'unset')\n"
        "delta = {'type': 'text_delta', 'text': 'ceiling=' + value}\n"
        "print(json.dumps({'type': 'stream_event', 'event': {'delta': delta}}), flush=True)\n"
        f"print({RESULT!r}, flush=True)\n"
    )
    monkeypatch.setattr(runner, "build_argv", lambda **_: [sys.executable, "-I", str(fake)])

    async def scenario():
        return [ev async for ev in run_agent("claude", prompt="hi", binary=sys.executable)]

    events = asyncio.run(asyncio.wait_for(scenario(), 20))
    assert TextDelta("ceiling=0") in events


def test_a_ceiling_the_host_chose_for_claude_is_kept():
    env = {runner.CLAUDE_BG_WAIT_CEILING_ENV: "3600000"}
    runner.claude_background_wait(env)
    assert env[runner.CLAUDE_BG_WAIT_CEILING_ENV] == "3600000"
    fresh: dict[str, str] = {}
    runner.claude_background_wait(fresh)
    assert fresh == {runner.CLAUDE_BG_WAIT_CEILING_ENV: "0"}


def test_claude_runs_with_the_profile_of_its_code_root(tmp_path, monkeypatch):
    """A session D3SKHAND starts in a work project uses that root's Claude Code profile.

    ``~/.claude-profiles`` (the user's own setup) maps a code root to its config dir;
    the shell's ``claude`` function applies it, and so must the runner, which bypasses the shell.
    """
    home, root = tmp_path / "home", tmp_path / "WorkCode"
    (root / "proj").mkdir(parents=True)
    home.mkdir()
    (home / ".claude-profiles").write_text(f"{root.resolve().as_posix()}\t/profiles/work\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    fake = tmp_path / "fake_claude.py"
    fake.write_text(
        "import json, os\n"
        "delta = {'type': 'text_delta', 'text': 'cfg=' + os.environ.get('CLAUDE_CONFIG_DIR', '')}\n"
        "print(json.dumps({'type': 'stream_event', 'event': {'delta': delta}}), flush=True)\n"
        f"print({RESULT!r}, flush=True)\n"
    )
    monkeypatch.setattr(runner, "build_argv", lambda **_: [sys.executable, "-I", str(fake)])

    async def scenario(cwd):
        return [ev async for ev in run_agent("claude", prompt="hi", binary=sys.executable, cwd=str(cwd))]

    assert TextDelta("cfg=/profiles/work") in asyncio.run(asyncio.wait_for(scenario(root / "proj"), 20))
    assert TextDelta("cfg=") in asyncio.run(asyncio.wait_for(scenario(tmp_path), 20))
