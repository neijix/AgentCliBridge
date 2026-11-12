using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Copilot;

/// <summary>
/// GitHub Copilot CLI JSONL (schema captured live 2026-07). Text streams as
/// <c>assistant.message_delta</c> (<c>data.deltaContent</c>); <c>assistant.message</c> repeats the whole
/// text and is used only when no delta carried that message. <c>assistant.reasoning_delta</c> is
/// thinking, never answer text. <c>result</c> carries the <c>sessionId</c> and the exit code
/// (<see cref="CopilotStatus"/>).
/// </summary>
/// <param name="activity">Whether thinking and tool events are shown.</param>
/// <param name="status">Filled with the exit code and error as they arrive; null keeps them to the parser.</param>
public sealed class CopilotParser(bool activity = true, CopilotStatus? status = null) : IOutputParser
{
    private readonly CopilotStatus _status = status ?? new CopilotStatus();

    /// <inheritdoc />
    public async IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var sessions = new SessionIds();
        var streamed = new HashSet<string>(StringComparer.Ordinal);
        await foreach (var item in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
        {
            if (!item.Parsed || item.Value is not JsonObject line)
            {
                continue;
            }

            foreach (var piece in LineEvents(line, sessions, streamed))
            {
                yield return piece;
            }
        }
    }

    private List<StreamEvent> LineEvents(JsonObject line, SessionIds sessions, HashSet<string> streamed)
    {
        var type = Json.AsString(line["type"]) ?? "";
        var data = line["data"];
        if (type == "result")
        {
            return ResultEvents(line, sessions);
        }

        if (type == "session.error")
        {
            var message = Json.AsString(Json.AsObject(data)["message"]);
            _status.PendingError = !string.IsNullOrEmpty(message) ? message : _status.PendingError ?? "Copilot CLI reported an error";
            return [];
        }

        if (data is not JsonObject body)
        {
            return [];
        }

        return TextEvents(type, body, streamed) ?? (activity ? ActivityEvents(type, body) : []);
    }

    private List<StreamEvent> ResultEvents(JsonObject line, SessionIds sessions)
    {
        if (line["exitCode"] is JsonValue code && code.TryGetValue<int>(out var exit))
        {
            _status.ResultExit = exit;
        }

        var update = sessions.Dedupe(line["sessionId"]);
        return update is null ? [] : [update];
    }

    /// <summary>Answer text, or null when this is not an assistant message.</summary>
    private static List<StreamEvent>? TextEvents(string type, JsonObject data, HashSet<string> streamed)
    {
        if (type == "assistant.message_delta")
        {
            var delta = Json.AsString(data["deltaContent"]);
            if (string.IsNullOrEmpty(delta))
            {
                return [];
            }

            streamed.Add(MessageKey(data));
            return [new TextDelta(delta)];
        }

        if (type == "assistant.message")
        {
            var content = Json.AsString(data["content"]);
            return !string.IsNullOrEmpty(content) && !streamed.Contains(MessageKey(data)) ? [new TextDelta(content)] : [];
        }

        return null;
    }

    private static string MessageKey(JsonObject data) => data["messageId"]?.ToJsonString() ?? "null";

    private static List<StreamEvent> ActivityEvents(string type, JsonObject data)
    {
        switch (type)
        {
            case "assistant.reasoning_delta":
                var delta = Json.AsString(data["deltaContent"]);
                return string.IsNullOrEmpty(delta) ? [] : [new ThinkingDelta(delta)];
            case "tool.execution_start":
                return [new ToolCall(TextOr(data["toolCallId"], ""), TextOr(data["toolName"], "tool"), Arguments(data["arguments"]))];
            case "tool.execution_complete":
                var (output, isError) = ResultText(data);
                var shown = new JsonObject();
                foreach (var key in new[] { "result", "error" })
                {
                    if (data[key] is { } value)
                    {
                        shown[key] = value.DeepClone();
                    }
                }

                return [new ToolResult(TextOr(data["toolCallId"], ""), output, isError, Json.RawText(shown.Count > 0 ? shown : null, output))];
            default:
                return [];
        }
    }

    private static JsonNode Arguments(JsonNode? arguments) => Json.IsTruthy(arguments) ? arguments!.DeepClone() : new JsonObject();

    /// <summary>The text of a truthy value (a number as its JSON text), else <paramref name="fallback"/>.</summary>
    private static string TextOr(JsonNode? value, string fallback) =>
        !Json.IsTruthy(value) ? fallback : Json.AsString(value) ?? value!.ToJsonString();

    private static (string Output, bool IsError) ResultText(JsonObject data)
    {
        var isError = data["success"] is JsonValue ok && ok.TryGetValue<bool>(out var success) && !success;
        if (data["result"] is JsonObject result && Json.AsString(result["content"]) is { } content)
        {
            return (content, isError);
        }

        var error = data["error"];
        if (error is JsonObject detail)
        {
            error = detail["message"];
        }

        return (TextOr(error, ""), isError);
    }
}
