using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Cursor;

/// <summary>Cursor Agent's stream-json stdout: assistant text, thinking, tool calls and the result.</summary>
/// <param name="Activity">Whether thinking and tool calls are shown; off keeps only text, session and errors.</param>
/// <param name="AfterResult">Started when a result ends the turn and no background agent is still working; null for none.</param>
public sealed record CursorParser(bool Activity = true, TurnDeadline? AfterResult = null) : IOutputParser
{
    private static readonly string[] OutputFields = ["interleavedOutput", "stdout", "content", "output", "error", "message"];

    /// <inheritdoc />
    public async IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var state = new ClaudeTurnState();
        await foreach (var item in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
        {
            if (item.Value is not JsonObject evt) continue;
            foreach (var piece in Handle(evt, state)) yield return piece;
        }
    }

    /// <summary>
    /// Streaming text from an assistant event. Real-time deltas carry <c>timestamp_ms</c> and omit
    /// <c>model_call_id</c>; the buffered flushes before tool calls and at the end of a turn are skipped,
    /// or the text would be shown twice (cursor.com/docs/cli/headless).
    /// </summary>
    public static string ExtractText(JsonObject evt)
    {
        if (!Json.IsTruthy(evt["timestamp_ms"]) || Json.IsTruthy(evt["model_call_id"])) return "";
        var parts = (evt["message"] as JsonObject)?["content"] as JsonArray;
        if (parts is not { Count: > 0 }) return "";
        return parts[0] is JsonObject first ? Json.AsString(first["text"]) ?? "" : "";
    }

    private IEnumerable<StreamEvent> Handle(JsonObject evt, ClaudeTurnState state)
    {
        var type = Json.AsString(evt["type"]);
        var subtype = Json.AsString(evt["subtype"]);
        if (type == "result") return ClaudeStream.Result(evt, state, AfterResult, null);
        if (type == "system" && subtype == "init") return ClaudeStream.InitSession(evt, state.Sessions);
        if (type == "system" && subtype == "background_tasks_changed")
        {
            state.HasBackgroundAgents = ClaudeStream.RunsBackgroundAgents(evt);
            return [];
        }
        if (type == "assistant")
        {
            var text = ExtractText(evt);
            if (text.Length == 0) return [];
            state.Seen = true;
            return [new TextDelta(text)];
        }
        return Activity && type is "thinking" or "tool_call" ? Events(evt, type) : [];
    }

    /// <summary>ThinkingDelta, ToolCall or ToolResult from a <c>thinking</c> or <c>tool_call</c> event.</summary>
    private static IEnumerable<StreamEvent> Events(JsonObject evt, string type)
    {
        var subtype = Json.AsString(evt["subtype"]);
        if (type == "thinking")
        {
            if (subtype == "delta" && Json.AsString(evt["text"]) is { Length: > 0 } text) yield return new ThinkingDelta(text);
            yield break;
        }
        if (evt["tool_call"] is not JsonObject call) yield break;
        var callId = Text((Json.IsTruthy(evt["call_id"]) ? evt["call_id"] : call["toolCallId"]));
        foreach (var (key, node) in call)
        {
            if (!key.EndsWith("ToolCall", StringComparison.Ordinal) || node is not JsonObject body) continue;
            var name = key.Length > "ToolCall".Length ? key[..^"ToolCall".Length] : "tool";
            if (subtype == "started")
            {
                yield return new ToolCall(callId, name, ScalarArguments(body["args"]));
                yield break;
            }
            if (subtype == "completed")
            {
                var (output, isError) = ResultText(body["result"]);
                yield return new ToolResult(callId, output, isError, Json.RawText(body["result"], output));
                yield break;
            }
        }
    }

    /// <summary>Cursor attaches parser internals (<c>parsingResult</c>, ...) to tool args: keep plain values.</summary>
    private static JsonNode ScalarArguments(JsonNode? args)
    {
        if (args is not JsonObject obj) return Json.IsTruthy(args) ? args!.DeepClone() : new JsonObject();
        var kept = new JsonObject();
        foreach (var (key, value) in obj)
        {
            var plain = value is JsonValue && value.GetValueKind() is not System.Text.Json.JsonValueKind.Null;
            if (plain && Json.AsString(value) != "" && key != "toolCallId") kept[key] = value!.DeepClone();
        }
        return kept;
    }

    /// <summary>Cursor tool results are <c>{"success": {...}}</c> or an error-like key.</summary>
    private static (string Output, bool IsError) ResultText(JsonNode? result)
    {
        if (result is not JsonObject obj) return ("", false);
        foreach (var (key, body) in obj)
        {
            var isError = key != "success";
            if (Json.AsString(body) is { } direct) return (direct, isError);
            if (body is not JsonObject fields) continue;
            foreach (var field in OutputFields)
            {
                if (Json.AsString(fields[field]) is { Length: > 0 } value) return (value, isError);
            }
            return (Json.Dumps(fields), isError);
        }
        return ("", false);
    }

    private static string Text(JsonNode? value) => value is null ? "" : Json.AsString(value) ?? value.ToJsonString();
}
