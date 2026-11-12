"""The chat wire format: ``to_wire`` on every event class, ``sse_frame``, and ``fold`` against the shared fixtures.

``tests/wire/*.json`` are also folded by ``AgentStream.fold`` in ``tests/ui/wire_contract.test.cjs``,
so the Python and the JavaScript fold cannot drift apart.
"""
import json
import subprocess
import sys
import typing
from pathlib import Path

import pytest

from agent_cli_bridge import events, wire
from agent_cli_bridge.events import (
    ActionBlocked,
    ApprovalRequest,
    Completed,
    InjectionDetected,
    InputAccepted,
    ModeChanged,
    SessionUpdate,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)

FIXTURES = sorted((Path(__file__).parent / "wire").glob("*.json"))
REPO_ROOT = Path(__file__).resolve().parent.parent

# one sample per event class and the frame it must become (without the "v" key)
SAMPLES: dict[type, tuple[object, str, dict]] = {
    TextDelta: (TextDelta("hi"), "text", {"text": "hi"}),
    ThinkingDelta: (ThinkingDelta("hm"), "thinking", {"text": "hm"}),
    ToolCall: (
        ToolCall("c1", "Read", {"file_path": "a"}),
        "tool_call",
        {"call_id": "c1", "name": "Read", "arguments": {"file_path": "a"}},
    ),
    ToolResult: (
        ToolResult("c1", "ok", True),
        "tool_result",
        {"call_id": "c1", "output": "ok", "is_error": True},
    ),
    ApprovalRequest: (
        ApprovalRequest("r1", "c1", "Bash", {"command": "ls"}, "run ls"),
        "approval_request",
        {"approval_id": "r1", "call_id": "c1", "name": "Bash", "arguments": {"command": "ls"}, "description": "run ls"},
    ),
    InjectionDetected: (
        InjectionDetected("c1", "Read", ("role-override", "exfil"), "ignore previous", "/log/1"),
        "injection_detected",
        {
            "call_id": "c1",
            "tool_name": "Read",
            "rules": ["role-override", "exfil"],
            "excerpt": "ignore previous",
            "details_url": "/log/1",
        },
    ),
    ActionBlocked: (
        ActionBlocked("r1", "c1", "Bash", {"command": "rm"}, "tainted turn", "/log/2"),
        "action_blocked",
        {"call_id": "c1", "name": "Bash", "reason": "tainted turn", "details_url": "/log/2"},
    ),
    InputAccepted: (InputAccepted("more"), "input_accepted", {}),
    ModeChanged: (ModeChanged("plan"), "permission_mode", {"mode": "plan"}),
    SessionUpdate: (SessionUpdate("s1"), "session", {"session_id": "s1"}),
    StreamError: (StreamError("boom"), "error", {"message": "boom", "code": "cli_agent_failed"}),
    Completed: (Completed(3), "done", {"returncode": 3}),
}


@pytest.mark.parametrize("event_class", typing.get_args(events.StreamEvent), ids=lambda cls: cls.__name__)
def test_to_wire_maps_every_event_class(event_class):
    assert event_class in SAMPLES, f"{event_class.__name__} has no wire mapping sample: map it in wire.to_wire"
    event, name, fields = SAMPLES[event_class]
    assert wire.to_wire(event) == (name, {"v": 1, **fields})


def test_to_wire_returns_none_for_other_objects():
    assert wire.to_wire(object()) is None
    assert wire.to_wire("text") is None
    assert wire.to_wire(None) is None


def test_to_wire_frame_has_no_truncated_key_when_nothing_is_cut():
    _, data = wire.to_wire(ToolResult("c1", "x" * 20000))
    assert "truncated" not in data
    assert len(data["output"]) == 20000


def test_tool_output_is_cut_at_the_limit_and_flagged():
    assert wire.to_wire(ToolResult("c1", "x" * 25000)) == (
        "tool_result",
        {"v": 1, "call_id": "c1", "output": "x" * 20000, "is_error": False, "truncated": True},
    )


def test_output_limit_is_a_parameter():
    _, data = wire.to_wire(ToolResult("c1", "abcdef"), output_limit=4)
    assert data["output"] == "abcd"
    assert data["truncated"] is True


def test_non_string_output_becomes_its_str():
    _, data = wire.to_wire(ToolResult("c1", ["a", 1]))  # type: ignore[arg-type]
    assert data["output"] == "['a', 1]"
    _, data = wire.to_wire(ToolResult("c1", None))  # type: ignore[arg-type]
    assert data["output"] == "None"


def test_is_error_is_a_bool():
    _, data = wire.to_wire(ToolResult("c1", "x", 1))  # type: ignore[arg-type]
    assert data["is_error"] is True


def test_approval_description_and_injection_excerpt_are_capped():
    _, approval = wire.to_wire(ApprovalRequest("r1", "c1", "Bash", {}, "d" * 30), output_limit=10)
    assert approval["description"] == "d" * 10
    assert approval["truncated"] is True
    _, injection = wire.to_wire(InjectionDetected("c1", "Read", ("r",), "e" * 30), output_limit=10)
    assert injection["excerpt"] == "e" * 10
    assert injection["truncated"] is True


def test_mode_error_is_present_only_when_non_empty_and_capped():
    _, accepted = wire.to_wire(ModeChanged("plan"))
    assert "error" not in accepted
    _, refused = wire.to_wire(ModeChanged("bypassPermissions", "not allowed here" * 5), output_limit=12)
    assert refused["mode"] == "bypassPermissions"
    assert refused["error"] == ("not allowed here" * 5)[:12]
    assert refused["truncated"] is True


def test_non_json_arguments_become_a_string():
    assert wire.to_wire(ToolCall("c2", "X", {1, 2})) == (
        "tool_call",
        {"v": 1, "call_id": "c2", "name": "X", "arguments": "{1, 2}"},
    )


def test_circular_arguments_become_a_string():
    loop: list = []
    loop.append(loop)
    _, data = wire.to_wire(ToolCall("c2", "X", loop))
    assert data["arguments"] == "[[...]]"
    json.dumps(data)


def test_huge_non_json_arguments_are_cut_and_flagged():
    _, data = wire.to_wire(ToolCall("c2", "X", {"k" * 10000}))
    assert len(data["arguments"]) == wire.ARGUMENTS_LIMIT
    assert data["truncated"] is True


def test_oversized_arguments_become_their_truncated_json_string():
    arguments = {"content": "é" * 9000}
    encoded = json.dumps(arguments, ensure_ascii=False)
    _, data = wire.to_wire(ToolCall("c3", "Write", arguments))
    assert data["arguments"] == encoded[: wire.ARGUMENTS_LIMIT]
    assert data["truncated"] is True


def test_arguments_at_the_limit_are_kept_as_they_are():
    # the JSON encoding of {"a": "<n x>"} is len(n) + 9 characters
    arguments = {"a": "x" * (wire.ARGUMENTS_LIMIT - 9)}
    assert len(json.dumps(arguments, ensure_ascii=False)) == wire.ARGUMENTS_LIMIT
    _, data = wire.to_wire(ToolCall("c3", "Write", arguments))
    assert data["arguments"] == arguments
    assert "truncated" not in data


def test_arguments_limit_applies_to_approval_requests_too():
    _, data = wire.to_wire(ApprovalRequest("r1", "c1", "Write", {"content": "x" * 9000}))
    assert isinstance(data["arguments"], str)
    assert data["truncated"] is True


@pytest.mark.parametrize("event_class", typing.get_args(events.StreamEvent), ids=lambda cls: cls.__name__)
def test_every_frame_is_json_serialisable_even_with_hostile_values(event_class):
    event = SAMPLES[event_class][0]
    hostile = {object(), 1j}
    if isinstance(event, ToolCall):
        event = ToolCall("c", "X", hostile)
    elif isinstance(event, ApprovalRequest):
        event = ApprovalRequest("r", "c", "X", hostile, "d")
    elif isinstance(event, ActionBlocked):
        event = ActionBlocked("r", "c", "X", hostile, "why")
    name, data = wire.to_wire(event)
    json.dumps(data)
    wire.sse_frame(name, data)


def test_sse_frame_is_one_ascii_line_of_json():
    assert wire.sse_frame("text", {"v": 1, "text": "a\nbé"}) == 'event: text\ndata: {"v": 1, "text": "a\\nb\\u00e9"}\n\n'


def test_sse_frame_keeps_app_extra_keys():
    frame = wire.sse_frame("tool_result", {"v": 1, "call_id": "c", "output": "o", "is_error": False, "scout": True})
    body = json.loads(frame.splitlines()[1].removeprefix("data: "))
    assert body["scout"] is True


def test_sse_frame_of_a_to_wire_frame_round_trips():
    name, data = wire.to_wire(ToolResult("c1", "line1\nline2\r\nüñ"))
    lines = wire.sse_frame(name, data).split("\n")
    assert lines[0] == f"event: {name}"
    assert lines[1].isascii()
    assert json.loads(lines[1].removeprefix("data: ")) == data
    assert lines[2:] == ["", ""]


@pytest.mark.parametrize("name", ["a\nb", "a\rb", "x\r\n"])
def test_sse_frame_rejects_a_name_with_a_line_break(name):
    with pytest.raises(ValueError):
        wire.sse_frame(name, {"v": 1})


def test_wire_import_is_stdlib_only():
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import agent_cli_bridge.wire; "
        "bad = sorted(m for m in ('fastapi', 'starlette', 'uvicorn', 'pydantic', 'httpx') if m in sys.modules); "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(REPO_ROOT)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wire_version_is_one():
    assert wire.WIRE_VERSION == 1
    assert wire.ARGUMENTS_LIMIT == 8192


def test_fixtures_exist_and_cover_tool_extras():
    names = {path.stem for path in FIXTURES}
    assert len(FIXTURES) >= 6
    assert "tool_extras" in names


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_contract_fixture(fixture):
    case = json.loads(fixture.read_text(encoding="utf-8"))
    assert set(case) == {"description", "frames", "parts"}
    parts: list = []
    for name, data in case["frames"]:
        assert wire.fold(parts, name, data) is None
    assert parts == case["parts"]


def test_fold_merges_into_the_given_list_in_place():
    parts: list = []
    wire.fold(parts, "text", {"v": 1, "text": "a"})
    first = parts[0]
    wire.fold(parts, "text", {"v": 1, "text": "b"})
    assert parts == [{"type": "text", "text": "ab"}]
    assert parts[0] is first


def test_to_wire_frames_fold_into_the_stored_message():
    parts: list = []
    for event in (
        TextDelta("Hel"),
        TextDelta("lo"),
        ToolCall("c1", "Read", {"file_path": "a"}),
        ToolResult("c1", "y" * 30, False),
        SessionUpdate("s1"),
        Completed(0),
    ):
        name, data = wire.to_wire(event, output_limit=20)  # type: ignore[misc]
        wire.fold(parts, name, data)
    assert parts == [
        {"type": "text", "text": "Hello"},
        {
            "type": "tool",
            "call_id": "c1",
            "name": "Read",
            "arguments": {"file_path": "a"},
            "output": "y" * 20,
            "is_error": False,
            "done": True,
            "truncated": True,
        },
    ]


def test_nan_and_infinity_arguments_become_a_string():
    # json.dumps would write the bare tokens NaN / Infinity, which JSON.parse in the page rejects
    _, data = wire.to_wire(ToolCall("c4", "X", {"n": float("nan")}))
    assert data["arguments"] == "{'n': nan}"
    _, data = wire.to_wire(ApprovalRequest("r1", "c1", "X", [float("inf")], "d"))
    assert data["arguments"] == "[inf]"
    assert "NaN" not in wire.sse_frame("tool_call", data) and "Infinity" not in wire.sse_frame("tool_call", data)
    json.loads(json.dumps(data), parse_constant=lambda token: pytest.fail(token))


def test_fold_treats_a_missing_or_null_text_as_empty():
    parts: list = []
    wire.fold(parts, "text", {"v": 1, "text": None})
    wire.fold(parts, "text", {"v": 1})
    wire.fold(parts, "text", {"v": 1, "text": "a"})
    wire.fold(parts, "thinking", {"v": 1, "text": None})
    assert parts == [{"type": "text", "text": "a"}, {"type": "thinking", "text": ""}]


def test_fold_treats_a_null_result_output_and_flag_as_the_defaults():
    parts: list = []
    wire.fold(parts, "tool_call", {"call_id": "c1", "name": "X", "arguments": {}})
    wire.fold(parts, "tool_result", {"call_id": "c1", "output": None, "is_error": None})
    assert parts[0]["output"] == ""
    assert parts[0]["is_error"] is False
    assert parts[0]["done"] is True


@pytest.mark.parametrize("data", [None, "text", ["text"], 3])
def test_fold_ignores_data_that_is_not_an_object(data):
    parts: list = [{"type": "text", "text": "a"}]
    for name in ("text", "thinking", "tool_call", "tool_result", "done"):
        wire.fold(parts, name, data)
    assert parts == [{"type": "text", "text": "a"}]
