"""Stream contracts: a recorded CLI turn replayed through the real runner, end to end.

Each ``tests/streams/<command>__<scenario>.jsonl`` is what a CLI printed on stdout for one turn
(a live capture, trimmed and redacted; ``tests/streams/capture.py`` records a new one). The
sibling ``.expected.jsonl`` holds every event ``run_agent`` must yield for it, one per line, so a
CLI release that changes its stream format, or a parser change that breaks an old format, fails
here with a readable diff.

After an intended parser change, regenerate the expected files and review their diff:
``ACB_UPDATE_STREAMS=1 python -m pytest tests/test_stream_contracts.py``.
"""
import asyncio
import dataclasses
import json
import os
from pathlib import Path

import pytest

from agent_cli_bridge import run_agent
from agent_cli_bridge.events import ToolResult

STREAMS = Path(__file__).parent / "streams"
CASES = sorted(STREAMS.glob("*__*.jsonl"))
CASES = [case for case in CASES if not case.name.endswith(".expected.jsonl")]
IS_UPDATING = os.environ.get("ACB_UPDATE_STREAMS") == "1"


def as_record(event) -> dict:
    """An event as a JSON-ready dict: its class name, then its fields (tuples become lists)."""
    fields = dataclasses.asdict(event)
    if isinstance(event, ToolResult) and not event.raw:
        del fields["raw"]  # recorded before the field existed; only an unwrapped result has it
    return json.loads(json.dumps({"event": type(event).__name__, **fields}))


def replay(binary: str, command: str) -> list[dict]:
    async def collect():
        return [
            as_record(event)
            async for event in run_agent(command, prompt="hi", binary=binary, activity=True, web_scout=False)
        ]

    return asyncio.run(collect())


def test_every_flavor_with_a_parser_has_a_recorded_turn():
    commands = {case.name.split("__")[0] for case in CASES}
    assert {"claude", "agent", "agy", "copilot", "grok", "opencode"} <= commands


@pytest.mark.parametrize("stream", CASES, ids=[case.stem for case in CASES])
def test_a_recorded_turn_yields_its_expected_events(stream, fake_cli):
    command = stream.name.split("__")[0]
    actual = replay(fake_cli(stream), command)
    expected_file = stream.with_name(stream.stem + ".expected.jsonl")
    if IS_UPDATING:
        expected_file.write_text("".join(json.dumps(record) + "\n" for record in actual), encoding="utf-8")
    assert expected_file.exists(), f"no {expected_file.name}: run with ACB_UPDATE_STREAMS=1 and review it"
    expected = [json.loads(line) for line in expected_file.read_text(encoding="utf-8").splitlines() if line]
    assert actual == expected


# A line any CLI might print that is valid JSON but not the object a parser expects, or an object
# whose nested field has the wrong type. Antigravity shows a non-object line as prose, by design.
_NOT_OBJECTS = ["null", "42", "[]", '"text"', "true"]
_WRONG_FIELDS = {
    "claude": ['{"type": "stream_event", "event": "x"}', '{"type": "stream_event", "event": {"delta": 7}}',
               '{"type": "control_response", "response": "x"}', '{"type": "assistant", "message": "x"}'],
    "grok": ['{"type": "stream_event", "event": "x"}', '{"type": "user", "message": []}'],
    "agy": ['{"event": "step_update", "step_update": "x"}', '{"event": "step_update", "step_update": []}'],
    "agent": ['{"type": "assistant", "message": "x"}', '{"type": "tool_call", "tool_call": "x"}'],
    "copilot": ['{"type": "assistant.message_delta", "data": "x"}'],
    "opencode": ['{"type": "text", "part": "x"}'],
}


@pytest.mark.parametrize("stream", CASES, ids=[case.stem for case in CASES])
def test_a_line_that_is_not_the_expected_object_changes_nothing(stream, fake_cli):
    command = stream.name.split("__")[0]
    junk = ([] if command == "agy" else _NOT_OBJECTS) + _WRONG_FIELDS[command]
    lines = stream.read_text(encoding="utf-8").splitlines()
    noisy = "\n".join([*junk, *lines[:1], *junk, *lines[1:]]) + "\n"
    expected_file = stream.with_name(stream.stem + ".expected.jsonl")
    expected = [json.loads(line) for line in expected_file.read_text(encoding="utf-8").splitlines() if line]
    assert replay(fake_cli(noisy), command) == expected
