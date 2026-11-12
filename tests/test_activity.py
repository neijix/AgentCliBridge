"""Activity events (thinking, tool calls, tool results) parsed from each CLI's stream.

Each stream mirrors a live capture (2026-09-13), trimmed to the fields the
parser reads. A fake CLI binary prints it, so the real runner parses it end to end.
"""
import asyncio
import json

from agent_cli_bridge import run_agent
from agent_cli_bridge.argv import build_argv
from agent_cli_bridge.events import (
    Completed,
    SessionUpdate,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)
from agent_cli_bridge.runner import OPENCODE_CHUNK_TIMEOUT_MS, opencode_config_content, opencode_directory


def _stream(records):
    return "".join(json.dumps(record) + "\n" for record in records)


def _run(fake_cli, command, records, activity=True):
    script = fake_cli(_stream(records))

    async def collect():
        return [
            event
            async for event in run_agent(command, prompt="hi", binary=str(script), activity=activity)
        ]

    return [e for e in asyncio.run(collect()) if not isinstance(e, (SessionUpdate, Completed))]


CLAUDE = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "thinking_delta", "thinking": "Let me look"}}},
    {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Let me look"}]}},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls", "description": "List"}}]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "a\nb", "is_error": False}]}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "denied"}],
         "is_error": True}]}},
    {"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
                                       "delta": {"type": "text_delta", "text": "Two files."}}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Two files."}]}},
    {"type": "result", "subtype": "success", "result": "Two files.", "session_id": "s1"},
]


def test_claude_activity_is_parsed_in_order(fake_cli):
    assert _run(fake_cli, "claude", CLAUDE) == [
        ThinkingDelta("Let me look"),
        ToolCall("t1", "Bash", {"command": "ls", "description": "List"}),
        ToolResult("t1", "a\nb", False),
        ToolResult("t2", "denied", True),
        TextDelta("Two files."),
    ]


def test_activity_is_off_by_default(fake_cli):
    assert _run(fake_cli, "claude", CLAUDE, activity=False) == [TextDelta("Two files.")]


def test_claude_error_result_is_a_stream_error_not_reply_text(fake_cli):
    # Live capture: OAuth expiry is a result with is_error, no text deltas.
    records = [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {"type": "result", "subtype": "error", "is_error": True,
         "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
         "session_id": "s1"},
    ]
    events = _run(fake_cli, "claude", records)
    assert len(events) == 1 and isinstance(events[0], StreamError)
    assert "OAuth session expired" in events[0].message
    assert events[0].code == "agent_error"


def test_claude_success_result_without_stream_is_still_text(fake_cli):
    records = [{"type": "result", "subtype": "success", "result": "Hello.", "session_id": "s1"}]
    assert _run(fake_cli, "claude", records) == [TextDelta("Hello.")]


def test_grok_streams_like_claude_and_its_tool_output_is_unwrapped(fake_cli):
    coloured = b"\x1b[34mhub\x1b[39;49m\x1b[0m\nnode\n"
    records = [
        {"type": "system", "subtype": "init", "session_id": "g1"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "c0", "name": "read_file", "input": {"target_file": "pyproject.toml"}},
            {"type": "tool_use", "id": "c1", "name": "run_terminal_command", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "c0",
             "content": json.dumps({"type": "ReadFile", "FileContent": {"content": "1→name"}}), "is_error": False},
            {"type": "tool_result", "tool_use_id": "c1",
             "content": json.dumps({"type": "Bash", "output": list(coloured)}), "is_error": False}]}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
                                           "delta": {"type": "text_delta", "text": "Done."}}},
        {"type": "result", "subtype": "success", "result": "Done.", "session_id": "g1"},
    ]
    assert _run(fake_cli, "grok", records) == [
        ToolCall("c0", "read_file", {"target_file": "pyproject.toml"}),
        ToolCall("c1", "run_terminal_command", {"command": "ls"}),
        ToolResult("c0", "1→name", False),
        ToolResult("c1", "hub\nnode\n", False),
        TextDelta("Done."),
    ]


def test_grok_cancelling_its_own_turn_is_reported_after_its_text(fake_cli):
    records = [
        {"type": "system", "subtype": "init", "session_id": "g1"},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                           "delta": {"type": "text_delta", "text": "Running tests."}}},
        {"type": "result", "subtype": "success", "result": "Running tests.", "stop_reason": "cancelled",
         "session_id": "g1"},
    ]
    events = _run(fake_cli, "grok", records)
    assert events[0] == TextDelta("Running tests.")
    assert isinstance(events[1], StreamError) and events[1].code == "cancelled"
    assert len(events) == 2


def test_grok_asks_for_partial_messages_so_text_streams():
    argv = build_argv(binary="grok", flavor="grok", prompt="hi")
    assert "--include-partial-messages" in argv


def test_cursor_activity(fake_cli):
    records = [
        {"type": "system", "subtype": "init", "session_id": "c1"},
        {"type": "thinking", "subtype": "delta", "text": "I will read", "timestamp_ms": 1},
        {"type": "thinking", "subtype": "completed", "timestamp_ms": 2},
        {"type": "tool_call", "subtype": "started", "call_id": "k1", "tool_call": {"shellToolCall": {
            "args": {"command": "ls agentdesk", "workingDirectory": "", "parsingResult": {"x": 1},
                     "description": "List"}}}},
        {"type": "tool_call", "subtype": "completed", "call_id": "k1", "tool_call": {"shellToolCall": {
            "args": {"command": "ls agentdesk"},
            "result": {"success": {"exitCode": 0, "stdout": "hub\n", "interleavedOutput": "hub\n"}}}}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "One."}]}, "timestamp_ms": 3},
        {"type": "result", "subtype": "success", "result": "One.", "session_id": "c1"},
    ]
    assert _run(fake_cli, "agent", records) == [
        ThinkingDelta("I will read"),
        ToolCall("k1", "shell", {"command": "ls agentdesk", "description": "List"}),
        ToolResult("k1", "hub\n", False),
        TextDelta("One."),
    ]


def test_antigravity_tool_steps_become_one_call_and_one_result(fake_cli):
    step = {"step_index": 2, "step_type": "tool", "tool_name": "view_file",
            "tool_info": {"name": "view_file", "parameters": {"AbsolutePath": "/p/pyproject.toml"}}}
    done = {**step, "state": "DONE", "tool_info": {**step["tool_info"], "output": "31 lines"}}
    records = [
        {"event": "init", "conversation_id": "a1"},
        {"event": "step_update", "step_update": {**step, "state": "ACTIVE"}},
        {"event": "step_update", "step_update": {**step, "state": "ACTIVE"}},
        {"event": "step_update", "step_update": done},
        {"event": "step_update", "step_update": {"step_index": 3, "state": "DONE",
                                                 "step_type": "agent_response", "text_delta": "Done."}},
        {"event": "result", "result": {"conversation_id": "a1"}},
    ]
    assert _run(fake_cli, "agy", records) == [
        ToolCall("2", "view_file", {"AbsolutePath": "/p/pyproject.toml"}),
        ToolResult("2", "31 lines", False),
        TextDelta("Done."),
    ]


COPILOT = [
    {"type": "assistant.reasoning_delta", "data": {"reasoningId": "r", "deltaContent": "I should"}},
    {"type": "assistant.reasoning", "data": {"reasoningId": "r", "content": "I should"}},
    {"type": "assistant.message", "data": {"messageId": "m0", "content": "", "toolRequests": [{"toolCallId": "x"}]}},
    {"type": "tool.execution_start", "data": {"toolCallId": "x", "toolName": "bash", "arguments": {"command": "ls"}}},
    {"type": "tool.execution_complete", "data": {"toolCallId": "x", "success": True, "result": {"content": "hub\n"}}},
    {"type": "assistant.message_delta", "data": {"messageId": "m1", "deltaContent": "The "}},
    {"type": "assistant.message_delta", "data": {"messageId": "m1", "deltaContent": "answer."}},
    {"type": "assistant.message", "data": {"messageId": "m1", "content": "The answer."}},
    {"type": "assistant.message", "data": {"messageId": "m2", "content": " Also this."}},
    {"type": "result", "sessionId": "p1", "exitCode": 0},
]


def test_copilot_activity_and_text_without_duplicates(fake_cli):
    assert _run(fake_cli, "copilot", COPILOT) == [
        ThinkingDelta("I should"),
        ToolCall("x", "bash", {"command": "ls"}),
        ToolResult("x", "hub\n", False),
        TextDelta("The "),
        TextDelta("answer."),
        TextDelta(" Also this."),
    ]


def test_copilot_reasoning_never_leaks_into_the_answer_text(fake_cli):
    assert _run(fake_cli, "copilot", COPILOT, activity=False) == [
        TextDelta("The "), TextDelta("answer."), TextDelta(" Also this."),
    ]


OPENCODE = [
    {"type": "step_start", "sessionID": "ses_1", "part": {"type": "step-start"}},
    {"type": "reasoning", "sessionID": "ses_1", "part": {"type": "reasoning", "text": "Read it first."}},
    {"type": "tool_use", "sessionID": "ses_1", "part": {
        "type": "tool", "tool": "read", "callID": "call_1",
        "state": {"status": "completed", "input": {"filePath": "/p/note.txt"}, "output": "1: hello"}}},
    {"type": "tool_use", "sessionID": "ses_1", "part": {
        "type": "tool", "tool": "bash", "callID": "call_2",
        "state": {"status": "error", "input": {"command": "ls /"},
                  "error": "The user rejected permission to use this specific tool call."}}},
    {"type": "step_finish", "sessionID": "ses_1", "part": {"type": "step-finish", "reason": "tool-calls"}},
    {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "It says hello."}},
    {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "Done."}},
    {"type": "step_finish", "sessionID": "ses_1", "part": {"type": "step-finish", "reason": "stop"}},
]


def test_opencode_parts_become_activity_and_paragraphs(fake_cli):
    assert _run(fake_cli, "opencode", OPENCODE) == [
        ThinkingDelta("Read it first."),
        ToolCall("call_1", "read", {"filePath": "/p/note.txt"}),
        ToolResult("call_1", "1: hello", False),
        ToolCall("call_2", "bash", {"command": "ls /"}),
        ToolResult("call_2", "The user rejected permission to use this specific tool call.", True),
        TextDelta("It says hello."),
        TextDelta("\n\nDone."),
    ]


def test_opencode_reports_its_session_id_once(fake_cli):
    script = fake_cli(_stream(OPENCODE))

    async def collect():
        return [event async for event in run_agent("opencode", prompt="hi", binary=str(script))]

    events = asyncio.run(collect())
    assert [e for e in events if isinstance(e, SessionUpdate)] == [SessionUpdate("ses_1")]
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta("It says hello."), TextDelta("\n\nDone.")]


def test_opencode_error_event_surfaces_the_provider_message(fake_cli):
    records = [{
        "type": "error", "sessionID": "ses_2",
        "error": {"name": "APIError", "data": {"message": "Upstream request failed: Model is unavailable.",
                                               "statusCode": 400}},
    }]
    events = _run(fake_cli, "opencode", records)
    assert len(events) == 1 and isinstance(events[0], StreamError)
    assert events[0].message == "Upstream request failed: Model is unavailable."


def _opencode_env(tmp_path, model, env=None):
    """The OPENCODE_CONFIG_CONTENT a fake `opencode` was started with (printed as text)."""
    script = tmp_path / "fake-opencode"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "text = os.environ.get('OPENCODE_CONFIG_CONTENT', '')\n"
        "print(json.dumps({'type': 'text', 'sessionID': 'ses_env', 'part': {'type': 'text', 'text': text}}))\n"
    )
    script.chmod(0o755)

    async def collect():
        return [
            event
            async for event in run_agent("opencode", prompt="hi", model=model, binary=str(script), env=env)
        ]

    texts = [e.text for e in asyncio.run(collect()) if isinstance(e, TextDelta)]
    return texts[0] if texts else ""


def test_opencode_gets_a_chunk_timeout_for_the_model_provider(tmp_path):
    # Without it a stalled provider stream kept a turn waiting forever.
    config = json.loads(_opencode_env(tmp_path, "openrouter/stealth/union-alpha", env={"PATH": "/usr/bin:/bin"}))
    assert config == {"provider": {"openrouter": {"options": {"chunkTimeout": OPENCODE_CHUNK_TIMEOUT_MS}}}}


def test_opencode_chunk_timeout_merges_with_the_host_config(tmp_path):
    host = {"provider": {"openrouter": {"options": {"baseURL": "http://proxy"}}}, "share": "disabled"}
    env = {"PATH": "/usr/bin:/bin", "OPENCODE_CONFIG_CONTENT": json.dumps(host)}
    config = json.loads(_opencode_env(tmp_path, "openrouter/stealth/union-alpha", env=env))
    assert config["share"] == "disabled"
    assert config["provider"]["openrouter"]["options"] == {
        "baseURL": "http://proxy", "chunkTimeout": OPENCODE_CHUNK_TIMEOUT_MS,
    }


def test_opencode_directory_publishes_the_project_as_pwd():
    env = {"PWD": "/wrong"}
    opencode_directory(env, "/code/app")
    assert env["PWD"] == "/code/app"
    untouched = {}
    opencode_directory(untouched, None)
    assert "PWD" not in untouched


def test_opencode_config_content_leaves_host_choices_alone():
    chosen = json.dumps({"provider": {"opencode": {"options": {"chunkTimeout": 5000}}}})
    assert opencode_config_content("opencode/big-pickle", chosen) is None
    assert opencode_config_content("opencode/big-pickle", "not json") is None
    assert opencode_config_content("opencode/big-pickle", "[1]") is None
    assert opencode_config_content("big-pickle", None) is None
    assert opencode_config_content(None, None) is None
