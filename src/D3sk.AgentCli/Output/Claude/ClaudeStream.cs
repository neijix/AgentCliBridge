using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Claude;

/// <summary>The line-level readers of the Claude stream-json protocol; Gemini and Grok call them too.</summary>
public static class ClaudeStream
{
    /// <summary>
    /// Whether Claude's <c>background_tasks_changed</c> lists an agent it still waits for. Claude Code ends a
    /// turn with a <c>result</c> while background subagents (or a workflow) keep working, then starts a new
    /// turn of its own when they report back. Background shell commands are not counted.
    /// </summary>
    public static bool RunsBackgroundAgents(JsonObject lineEvent) =>
        lineEvent["tasks"] is JsonArray tasks
        && tasks.OfType<JsonObject>().Any(task =>
        {
            var kind = Text(task["task_type"]);
            return kind.Contains("agent", StringComparison.Ordinal) || kind.Contains("workflow", StringComparison.Ordinal);
        });

    /// <summary>The session update of a <c>system</c>/<c>init</c> line, when its id is new.</summary>
    public static List<StreamEvent> InitSession(JsonObject lineEvent, SessionIds sessions) =>
        Session(lineEvent, sessions) is { } update ? [update] : [];

    /// <summary>ToolCall / ToolResult blocks of a Claude-protocol message (Claude Code, Grok).</summary>
    public static List<StreamEvent> ToolEvents(JsonObject lineEvent)
    {
        var events = new List<StreamEvent>();
        if (Json.AsObject(lineEvent["message"])["content"] is not JsonArray blocks)
        {
            return events;
        }

        var type = Json.AsString(lineEvent["type"]);
        foreach (var block in blocks.OfType<JsonObject>())
        {
            var blockType = Json.AsString(block["type"]);
            if (type == "assistant" && blockType == "tool_use")
            {
                var input = Json.IsTruthy(block["input"]) ? block["input"]!.DeepClone() : new JsonObject();
                events.Add(new ToolCall(Text(block["id"]), Text(block["name"], "tool"), input));
            }
            else if (type == "user" && blockType == "tool_result")
            {
                var content = block["content"];
                var text = ClaudeToolText.Flatten(content);
                events.Add(new ToolResult(Text(block["tool_use_id"]), text, Json.IsTruthy(block["is_error"]), ClaudeToolText.Raw(content, text)));
            }
        }

        return events;
    }

    /// <summary>Text and thinking deltas inside one <c>stream_event</c>.</summary>
    public static List<StreamEvent> Deltas(JsonObject lineEvent, bool activity, ClaudeTurnState state)
    {
        var delta = Json.AsObject(Json.AsObject(lineEvent["event"])["delta"]);
        var kind = Json.AsString(delta["type"]);
        if (kind == "text_delta" && Json.AsString(delta["text"]) is { Length: > 0 } text)
        {
            state.Seen = true;
            return [new TextDelta(text)];
        }

        if (activity && kind == "thinking_delta" && Json.AsString(delta["thinking"]) is { Length: > 0 } thinking)
        {
            return [new ThinkingDelta(thinking)];
        }

        return [];
    }

    /// <summary>
    /// One stream-json <c>result</c>: session id, error or fallback text, then the deadline.
    /// <paramref name="cancelMessage"/> is set only for Grok, when the turn was cancelled because a tool
    /// wanted an approval a headless run cannot give. On a live turn (<paramref name="live"/>) a resumed session's
    /// empty leftover result is skipped, and the deadline starts only once the turn took its last message and
    /// <paramref name="closeInput"/> closed stdin.
    /// </summary>
    public static List<StreamEvent> Result(
        JsonObject lineEvent, ClaudeTurnState state, TurnDeadline? afterResult, string? cancelMessage,
        LiveLines? live = null, Action? closeInput = null)
    {
        var events = new List<StreamEvent>();
        if (Session(lineEvent, state.Sessions) is { } update)
        {
            events.Add(update);
        }

        var isFailure = Json.IsTruthy(lineEvent["is_error"]) || Json.AsString(lineEvent["subtype"]) == "error";
        if (live?.IsEmptyResume(lineEvent, isFailure) == true)
        {
            return events; // not this turn's result: Claude takes the prompt next
        }

        if (isFailure)
        {
            state.Seen = true;
            events.Add(new StreamError(ErrorMessage(lineEvent), "agent_error"));
        }
        else if (!state.Seen && Json.AsString(lineEvent["result"]) is { Length: > 0 } resultText)
        {
            state.Seen = true;
            events.Add(new TextDelta(resultText));
        }

        // A message still on its way keeps a live turn open; Claude then answers it with a result of its own.
        var inputEnded = live is null || live.TurnEnded();
        if (live is not null && inputEnded)
        {
            closeInput?.Invoke();
        }

        // Background subagents still working mean Claude answers again once they report back.
        if (!state.HasBackgroundAgents && inputEnded)
        {
            afterResult?.Start();
        }

        if (!string.IsNullOrEmpty(cancelMessage))
        {
            state.Seen = true;
            events.Add(new StreamError(cancelMessage, "cancelled"));
        }

        return events;
    }

    /// <summary>
    /// Human text of a <c>result</c> marked <c>is_error</c> / <c>subtype: error</c>. Claude Code's OAuth
    /// expiry is this: no text deltas, then a result whose text is "Failed to authenticate…".
    /// </summary>
    public static string ErrorMessage(JsonObject lineEvent)
    {
        var result = lineEvent["result"];
        if (Json.AsString(result) is { } text && text.Trim().Length > 0)
        {
            return text.Trim();
        }

        if (result is JsonObject fields)
        {
            foreach (var key in new[] { "message", "error", "text" })
            {
                if (Json.AsString(fields[key]) is { } value && value.Trim().Length > 0)
                {
                    return value.Trim();
                }
            }
        }

        if (lineEvent["errors"] is JsonArray errors)
        {
            var parts = errors.Select(item => Text(item).Trim()).Where(part => part.Length > 0).ToList();
            if (parts.Count > 0)
            {
                return string.Join("\n", parts);
            }
        }

        return "The agent reported an error";
    }

    private static SessionUpdate? Session(JsonObject lineEvent, SessionIds sessions) =>
        sessions.Dedupe(Json.IsTruthy(lineEvent["session_id"]) ? lineEvent["session_id"] : lineEvent["chat_id"]);

    /// <summary>Python's <c>str(value or fallback)</c>: a string as is, another truthy value as its JSON.</summary>
    private static string Text(JsonNode? value, string fallback = "") =>
        !Json.IsTruthy(value) ? fallback : Json.AsString(value) ?? value!.ToJsonString();
}
