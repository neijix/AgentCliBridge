using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.OpenCode;

/// <summary>
/// OpenCode <c>run --format json</c> stdout (captured live 2026-09-17). Every event carries
/// <c>sessionID</c>. Text and reasoning arrive as whole parts, not deltas; a tool part arrives
/// finished. An error event (bad model, provider refusal) ends the run with exit 1 and no text.
/// </summary>
/// <param name="Activity">Whether reasoning and tool parts are shown, not only text and errors.</param>
public sealed record OpenCodeOutputParser(bool Activity = true) : IOutputParser
{
    /// <inheritdoc />
    public async IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var sessions = new SessionIds();
        HashSet<string> started = [];
        var seenText = false;
        await foreach (var item in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
        {
            if (!item.Parsed || item.Value is not JsonObject obj)
            {
                continue;
            }

            var update = sessions.Dedupe(obj["sessionID"], requireString: true);
            if (update is not null)
            {
                yield return update;
            }

            foreach (var piece in PartEvents(obj, started, ref seenText))
            {
                yield return piece;
            }
        }
    }

    private List<StreamEvent> PartEvents(JsonObject obj, HashSet<string> started, ref bool seenText)
    {
        var rawPart = obj["part"];
        if (Json.IsTruthy(rawPart) && rawPart is not JsonObject)
        {
            return [];
        }

        var part = Json.AsObject(rawPart);
        var type = Json.AsString(obj["type"]);
        if (type == "text")
        {
            if (Json.AsString(part["text"]) is not { Length: > 0 } text)
            {
                return [];
            }

            // Separate parts are separate paragraphs (one per step).
            var delta = new TextDelta(seenText ? $"\n\n{text}" : text);
            seenText = true;
            return [delta];
        }

        if (type == "error")
        {
            seenText = true;
            return [new StreamError(ErrorMessage(obj), "agent_error")];
        }

        if (!Activity)
        {
            return [];
        }

        return type switch
        {
            "reasoning" => Json.AsString(part["text"]) is { Length: > 0 } t ? [new ThinkingDelta(t)] : [],
            "tool_use" => ToolEvents(part, started),
            _ => [],
        };
    }

    /// <summary>A finished tool part is the call and its result; a part still running is only the call.</summary>
    private static List<StreamEvent> ToolEvents(JsonObject part, HashSet<string> started)
    {
        var callId = Text(part["callID"]) is { Length: > 0 } c ? c : Text(part["id"]);
        var rawState = part["state"];
        if (Json.IsTruthy(rawState) && rawState is not JsonObject)
        {
            return [];
        }

        var state = Json.AsObject(rawState);
        List<StreamEvent> events = [];
        if (started.Add(callId))
        {
            var input = Json.IsTruthy(state["input"]) ? state["input"]!.DeepClone() : new JsonObject();
            var name = Text(part["tool"]);
            events.Add(new ToolCall(callId, name.Length > 0 ? name : "tool", input));
        }

        switch (Json.AsString(state["status"]))
        {
            case "completed":
                events.Add(new ToolResult(callId, Json.AsString(state["output"]) ?? "", false));
                break;
            case "error":
                events.Add(new ToolResult(callId, Json.AsString(state["error"]) ?? "", true));
                break;
        }

        return events;
    }

    /// <summary><c>{"type":"error","error":{"name","data":{"message",…}}}</c> as the human message.</summary>
    private static string ErrorMessage(JsonObject obj)
    {
        var rawError = obj["error"];
        if (rawError is not null && rawError is not JsonObject && Json.IsTruthy(rawError))
        {
            return Text(rawError);
        }

        var error = Json.AsObject(rawError);
        var data = error["data"];
        if (data is JsonObject d && Json.AsString(d["message"]) is { Length: > 0 } message)
        {
            return message;
        }

        var name = Text(error["name"]) is { Length: > 0 } n ? n : "Open Router error";
        return Json.IsTruthy(data) ? $"{name}: {Json.Dumps(data)}" : name;
    }

    /// <summary>A JSON value as Python <c>str()</c> would show a scalar: a string as is, null and false as "", else its JSON text.</summary>
    private static string Text(JsonNode? value) =>
        Json.AsString(value) ?? (Json.IsTruthy(value) ? Json.Dumps(value) : "");
}
