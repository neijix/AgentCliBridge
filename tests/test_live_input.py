"""Tool approvals and messages added mid-turn (control.py), against a fake Claude Code.

The fake speaks the stdin/stdout stream-json protocol captured live from Claude Code
2.1.212 (2026-09-14): it echoes user messages with isReplay, asks before a tool with a
can_use_tool control_request, takes messages said while it waits at its next step, and
answers messages that arrive after a result before exiting on stdin EOF.
"""
import asyncio
import json
import sys

from agent_cli_bridge import run_agent, runner
from agent_cli_bridge.argv import build_argv
from agent_cli_bridge.control import TurnInput
from agent_cli_bridge.events import (
    ApprovalRequest,
    Completed,
    InputAccepted,
    ModeChanged,
    SessionUpdate,
    TextDelta,
    ToolCall,
    ToolResult,
)

FAKE_CLAUDE = r'''
import json, os, sys, time

log = open(os.environ["FAKE_LOG"], "a")
mode = os.environ["FAKE_MODE"]

def out(record):
    print(json.dumps(record), flush=True)

def read():
    line = sys.stdin.readline()
    if not line:
        return None
    log.write(line)
    log.flush()
    return json.loads(line)

def replay(message):
    out({"type": "user", "isReplay": True, "message": message["message"]})

prompt = read()
if mode == "stale":  # a resumed session reports what its last run left behind (claude 2.1.x)
    out({"type": "system", "subtype": "task_notification", "status": "stopped"})
    out({"type": "system", "subtype": "init", "session_id": "s1"})
    out({"type": "result", "subtype": "success", "result": "", "num_turns": 0, "session_id": "s1"})
    time.sleep(float(os.environ.get("FAKE_PAUSE", "0")))  # still thinking about the prompt
out({"type": "system", "subtype": "init", "session_id": "s1"})
if mode != "noreplay":  # a version that stops echoing the prompt
    replay(prompt)
if mode in ("approve", "unsupported"):
    if mode == "approve":
        out({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a"}}]}})
        out({"type": "control_request", "request_id": "r1", "request": {
            "subtype": "can_use_tool", "tool_name": "Edit", "input": {"file_path": "a"},
            "tool_use_id": "t1", "description": "Edit a"}})
    else:
        out({"type": "control_request", "request_id": "r1", "request": {"subtype": "hook_callback"}})
    said = []
    while True:
        message = read()
        if message["type"] == "control_response":
            break
        said.append(message)
    if mode == "approve":
        out({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "done", "is_error": False}]}})
    for message in said:  # taken at the next step, before the model answers
        replay(message)
if mode == "mode":  # answers set_permission_mode like Claude Code without the bypass flag
    for _ in range(2):
        request = read()
        asked = request["request"]["mode"]
        if asked == "bypassPermissions":
            out({"type": "control_response", "response": {"subtype": "error",
                 "request_id": request["request_id"], "error": "not launched with bypass"}})
        else:
            out({"type": "control_response", "response": {"subtype": "success",
                 "request_id": request["request_id"], "response": {"mode": asked}}})
out({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "first"}}})
out({"type": "result", "subtype": "success", "result": "first", "session_id": "s1"})
while True:  # a message that arrives after a result starts another turn
    message = read()
    if message is None:
        break
    replay(message)
    time.sleep(float(os.environ.get("FAKE_PAUSE", "0")))  # a long answer
    out({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "next"}}})
    out({"type": "result", "subtype": "success", "result": "next", "session_id": "s1"})
'''


def _fake(tmp_path):
    if sys.platform == "win32":  # no shebangs: a .cmd that runs the script with this Python
        (tmp_path / "fake_claude.py").write_text(FAKE_CLAUDE)
        script = tmp_path / "fake-claude.cmd"
        script.write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\n')
        return script
    script = tmp_path / "fake-claude"
    script.write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}")
    script.chmod(0o755)
    return script


def _run(tmp_path, mode, on_event, command="claude", turn_input=None, env=None):
    """Run the fake; ``on_event(event, turn_input)`` reacts while the turn streams."""
    log = tmp_path / "stdin.jsonl"
    turn_input = turn_input or TurnInput()

    async def collect():
        events = []
        async for event in run_agent(
            command, prompt="hi", binary=str(_fake(tmp_path)), activity=True, turn_input=turn_input,
            web_scout=False,  # its --settings JSON does not survive a .cmd; scout approvals: test_web_scout
            extra_env={"FAKE_LOG": str(log), "FAKE_MODE": mode, **(env or {})},
        ):
            events.append(event)
            on_event(event, turn_input)
        return events

    events = asyncio.run(asyncio.wait_for(collect(), 15))
    written = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return [e for e in events if not isinstance(e, SessionUpdate)], written, turn_input


def test_the_prompt_goes_to_stdin_and_the_cli_asks_through_stdio():
    argv = build_argv(binary="claude", flavor="claude", prompt="secret prompt", live_input=True)
    assert "secret prompt" not in argv
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert "--replay-user-messages" in argv
    assert "secret prompt" in build_argv(binary="claude", flavor="claude", prompt="secret prompt")


def test_an_approval_allows_exactly_the_call_the_cli_asked_about(tmp_path):
    answers = []

    def on_event(event, turn_input):
        if isinstance(event, ApprovalRequest):
            answers.append(turn_input.answer(event.request_id, True))
            answers.append(turn_input.answer(event.request_id, True))  # already answered
            answers.append(turn_input.answer("r-unknown", True))

    events, written, _ = _run(tmp_path, "approve", on_event)

    approval = next(e for e in events if isinstance(e, ApprovalRequest))
    assert approval == ApprovalRequest("r1", "t1", "Edit", {"file_path": "a"}, "Edit a")
    assert answers == [True, False, False]
    assert written[0]["message"] == {"role": "user", "content": "hi"}
    response = written[1]["response"]
    assert response["request_id"] == "r1"
    # Guard: only allow + the CLI's own input — no edited input, no permission rule or mode.
    assert response["response"] == {"behavior": "allow", "updatedInput": {"file_path": "a"}}
    assert [type(e) for e in events] == [ToolCall, ApprovalRequest, ToolResult, TextDelta, Completed]
    assert events[-1] == Completed(0)


def test_a_denial_carries_the_users_reason(tmp_path):
    def on_event(event, turn_input):
        if isinstance(event, ApprovalRequest):
            turn_input.answer(event.request_id, False, "  use git status instead ")

    _, written, _ = _run(tmp_path, "approve", on_event)
    assert written[1]["response"]["response"] == {"behavior": "deny", "message": "use git status instead"}


def test_a_message_said_while_the_agent_works_is_taken_at_its_next_step(tmp_path):
    def on_event(event, turn_input):
        if isinstance(event, ApprovalRequest):
            assert turn_input.say("also run the tests")
            turn_input.answer(event.request_id, True)

    events, _, turn_input = _run(tmp_path, "approve", on_event)

    kinds = [type(e) for e in events]
    assert kinds == [ToolCall, ApprovalRequest, ToolResult, InputAccepted, TextDelta, Completed]
    assert events[3] == InputAccepted("also run the tests")
    assert not turn_input.is_open and not turn_input.say("too late")


def test_a_message_said_as_the_turn_ends_is_answered_before_the_cli_exits(tmp_path):
    def on_event(event, turn_input):
        if event == TextDelta("first"):
            assert turn_input.say("one more thing")

    events, _, _ = _run(tmp_path, "plain", on_event)
    assert events == [TextDelta("first"), InputAccepted("one more thing"), TextDelta("next"), Completed(0)]


def test_the_grace_after_a_result_waits_for_a_message_still_being_answered(tmp_path, monkeypatch):
    """A result with a message still queued is not the end: no deadline cuts the answer."""
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.2)

    def on_event(event, turn_input):
        if event == TextDelta("first"):
            assert turn_input.say("one more thing")

    events, _, _ = _run(tmp_path, "plain", on_event, env={"FAKE_PAUSE": "1"})
    assert events == [TextDelta("first"), InputAccepted("one more thing"), TextDelta("next"), Completed(0)]


def test_a_stale_result_before_the_prompt_is_taken_does_not_end_the_turn(tmp_path, monkeypatch):
    """Regression (2026-10-12): resuming a session whose last run left a background shell
    command, Claude first sent an empty result for that task's notification (shapes captured
    live). The deadline it started stopped Claude mid-answer: "exited cleanly with no output"."""
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(runner, "_EXIT_GRACE_SECONDS", 0.2)

    events, written, _ = _run(tmp_path, "stale", lambda event, turn_input: None, env={"FAKE_PAUSE": "1"})
    assert events == [TextDelta("first"), Completed(0)]
    assert [m["type"] for m in written] == ["user"]


def test_a_result_still_ends_the_turn_when_claude_never_echoes_the_prompt(tmp_path, monkeypatch):
    """Only the stale result's exact shape is skipped: without the echo, the turn must not hang."""
    monkeypatch.setattr(runner, "RESULT_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(runner, "_EXIT_GRACE_SECONDS", 0.2)

    events, _, _ = _run(tmp_path, "noreplay", lambda event, turn_input: None)
    assert events == [TextDelta("first"), Completed(0)]


def test_a_message_said_before_the_cli_starts_follows_the_prompt(tmp_path):
    turn_input = TurnInput()
    assert turn_input.say("queued early")
    events, written, _ = _run(tmp_path, "plain", lambda *_: None, turn_input=turn_input)
    assert [w["message"]["content"] for w in written] == ["hi", "queued early"]
    assert InputAccepted("queued early") in events and events[-1] == Completed(0)


def test_unsupported_control_requests_are_refused_instead_of_left_waiting(tmp_path):
    events, written, _ = _run(tmp_path, "unsupported", lambda *_: None)
    assert written[1]["response"]["subtype"] == "error"
    assert written[1]["response"]["request_id"] == "r1"
    assert events[-1] == Completed(0)


def test_answering_a_question_allows_it_with_the_chosen_answers():
    """AskUserQuestion is allowed with an updatedInput carrying the user's picks."""
    written = []
    turn_input = TurnInput()
    turn_input._bind(lambda payload: (written.append(payload), True)[1])
    turn_input._asked("r1", {"questions": [{"question": "OS?"}, {"question": "Key?"}], "metadata": {"m": 1}})

    ok = turn_input.answer_question("r1", {"OS?": "macOS", "Key?": ["env", "file"]}, response="  ")

    assert ok is True
    assert written[-1]["response"]["response"] == {
        "behavior": "allow",
        "updatedInput": {
            "questions": [{"question": "OS?"}, {"question": "Key?"}],
            "metadata": {"m": 1},
            "answers": {"OS?": "macOS", "Key?": ["env", "file"]},
        },
    }
    assert turn_input.answer_question("r1", {"OS?": "macOS"}) is False  # already answered


def test_a_skipped_question_is_allowed_with_no_answers():
    written = []
    turn_input = TurnInput()
    turn_input._bind(lambda payload: (written.append(payload), True)[1])
    turn_input._asked("r1", {"questions": [{"question": "OS?"}]})

    assert turn_input.answer_question("r1", {}) is True
    assert written[-1]["response"]["response"] == {
        "behavior": "allow",
        "updatedInput": {"questions": [{"question": "OS?"}]},
    }


def test_answer_question_refuses_to_edit_a_gated_tools_input():
    """Guard: only AskUserQuestion (input has ``questions``) may run with a substituted input."""
    written = []
    turn_input = TurnInput()
    turn_input._bind(lambda payload: (written.append(payload), True)[1])
    turn_input._asked("r1", {"command": "rm -rf build"})

    assert turn_input.answer_question("r1", {"anything": "yes"}) is False
    assert written == []  # left pending: a normal allow/deny still applies
    assert turn_input.answer("r1", True) is True
    assert written[-1]["response"]["response"]["updatedInput"] == {"command": "rm -rf build"}


def test_other_clis_take_no_live_input(tmp_path):
    script = tmp_path / "fake-gemini"
    script.write_text("#!/bin/sh\necho '{\"type\":\"result\",\"response\":\"ok\"}'\n")
    script.chmod(0o755)
    turn_input = TurnInput()

    async def collect():
        return [event async for event in run_agent("gemini", prompt="hi", binary=str(script), turn_input=turn_input)]

    asyncio.run(collect())
    assert not turn_input.say("hello") and not turn_input.answer("r1", True)


def test_a_permission_mode_switch_reaches_the_running_cli_and_its_answer_comes_back(tmp_path):
    turn_input = TurnInput()
    assert turn_input.set_permission_mode("auto")  # before the CLI starts: sent right after the prompt
    assert not turn_input.set_permission_mode("yolo")  # not a mode

    def on_event(event, turn_input):
        if isinstance(event, ModeChanged) and event.mode == "auto":
            assert turn_input.set_permission_mode("bypassPermissions")

    events, written, turn_input = _run(tmp_path, "mode", on_event, turn_input=turn_input)

    assert written[1] == {
        "type": "control_request", "request_id": "d3sk-mode-1",
        "request": {"subtype": "set_permission_mode", "mode": "auto"},
    }
    assert events[:2] == [ModeChanged("auto"), ModeChanged("bypassPermissions", error="not launched with bypass")]
    assert events[-1] == Completed(0)
    assert not turn_input.set_permission_mode("plan")  # the turn is over
