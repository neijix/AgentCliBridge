"""Stderr is drained to a 256 KiB tail while the turn runs; stdin is not inherited."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from agent_cli_bridge import run_agent, runner
from agent_cli_bridge.events import Completed, StreamError, TextDelta

_STDERR_TAIL_BYTES = 256 * 1024

_STDERR_FLOOD = """\
import sys
sys.stderr.buffer.write(b"HEAD-MARKER")
sys.stderr.buffer.write(b"m" * (1024 * 1024))
sys.stderr.buffer.write(b"TAIL-MARKER")
sys.stderr.buffer.flush()
raise SystemExit(1)
"""

_BLOCKS_ON_STDIN = """\
import sys
sys.stdin.read()
print('{"type": "result", "result": "done"}')
"""

_GROK_ECHO = """\
import json, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
source = "argv"
if prompt == "-":
    prompt, source = sys.stdin.buffer.read().decode("utf-8"), "stdin"
print(json.dumps({"type": "result", "result": json.dumps([source, prompt])}))
"""

_CLAUDE_ECHO = """\
import json, sys
args = sys.argv[1:]
if "--" in args:
    prompt, source = args[args.index("--") + 1], "argv"
else:
    prompt, source = sys.stdin.buffer.read().decode("utf-8"), "stdin"
print(json.dumps({"type": "result", "result": json.dumps([source, prompt])}))
"""


def _launcher(tmp_path: Path, name: str, body: str) -> str:
    if sys.platform == "win32":
        (tmp_path / f"{name}.py").write_text(body)
        launcher = tmp_path / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" "%~dp0{name}.py" %*\n')
        return str(launcher)
    launcher = tmp_path / name
    launcher.write_text(f"#!{sys.executable}\n{body}")
    launcher.chmod(0o755)
    return str(launcher)


def _quiet(**kwargs: object) -> dict[str, object]:
    return {"web_scout": False, "guard": False, "security_log": False, **kwargs}


def test_stderr_tail_keeps_the_last_256_kib_so_one_mebibyte_still_finishes(tmp_path: Path):
    binary = _launcher(tmp_path, "flood", _STDERR_FLOOD)

    async def collect():
        return [
            event
            async for event in run_agent("claude", prompt="hi", binary=binary, **_quiet())
        ]

    events = asyncio.run(asyncio.wait_for(collect(), 8))
    errors = [event for event in events if isinstance(event, StreamError)]
    assert len(errors) == 1
    message = errors[0].message
    assert message.endswith("TAIL-MARKER")
    assert "HEAD-MARKER" not in message
    assert len(message.encode()) == _STDERR_TAIL_BYTES
    assert isinstance(events[-1], Completed)


def test_a_cli_that_blocks_on_stdin_still_finishes(tmp_path: Path):
    binary = _launcher(tmp_path, "blocks", _BLOCKS_ON_STDIN)
    saved = os.dup(0)
    read_fd, write_fd = os.pipe()
    os.dup2(read_fd, 0)
    os.close(read_fd)
    try:
        async def collect():
            return [
                event
                async for event in run_agent("claude", prompt="hi", binary=binary, **_quiet())
            ]

        events = asyncio.run(asyncio.wait_for(collect(), 5))
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(write_fd)
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    assert text == "done"
    assert isinstance(events[-1], Completed)
    assert events[-1].returncode == 0


def test_grok_prompt_from_stdin_is_delivered(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runner, "is_too_long", lambda argv: any(len(arg) > 1000 for arg in argv))
    prompt = "é" + "x" * 5000
    binary = _launcher(tmp_path, "grok", _GROK_ECHO)

    async def collect():
        return [
            event
            async for event in run_agent("grok", prompt=prompt, binary=binary, **_quiet())
        ]

    events = asyncio.run(asyncio.wait_for(collect(), 8))
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    source, received = json.loads(text)
    assert source == "stdin" and received == prompt


def _claude_prompt(tmp_path: Path, prompt: str) -> tuple[str, str]:
    binary = _launcher(tmp_path, "claude", _CLAUDE_ECHO)

    async def collect():
        return [
            event
            async for event in run_agent("claude", prompt=prompt, binary=binary, **_quiet())
        ]

    events = asyncio.run(asyncio.wait_for(collect(), 8))
    source, received = json.loads("".join(e.text for e in events if isinstance(e, TextDelta)))
    return source, received


def test_a_claude_prompt_that_looks_like_a_flag_arrives_as_the_prompt(tmp_path: Path):
    assert _claude_prompt(tmp_path, "--mcp-config={} hi") == ("argv", "--mcp-config={} hi")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's one-argument limit")
def test_a_claude_prompt_over_linuxs_argument_limit_goes_through_stdin(tmp_path: Path):
    """A long page as Claude's prompt failed with "Argument list too long"."""
    prompt = "é" + "page text. " * 20_000
    assert _claude_prompt(tmp_path, prompt) == ("stdin", prompt)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's one-argument limit")
def test_a_long_claude_prompt_with_a_lone_surrogate_still_reaches_the_cli(tmp_path: Path):
    source, received = _claude_prompt(tmp_path, "\ud800" + "page text. " * 20_000)
    assert source == "stdin" and received.startswith("?page text.")
