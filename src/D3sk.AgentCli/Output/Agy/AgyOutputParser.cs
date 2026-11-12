using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Agy;

/// <summary>
/// Antigravity's event stdout: prose lines, step updates and a conversation id. A line that is not
/// a JSON object is prose and becomes a <see cref="TextDelta"/> (a line that starts with <c>{</c> and
/// parses is always an object, so a parsed non-object stays text). The host's "text was seen" and
/// "result arrived" bookkeeping is not here: it reads the yielded events.
/// </summary>
public sealed class AgyOutputParser : IOutputParser
{
    // Live captures show DONE; the others are defensive guesses so a failed tool is not left "running".
    private static readonly HashSet<string> ToolEndStates = ["DONE", "ERROR", "FAILED", "CANCELED", "CANCELLED"];

    /// <summary>Whether tool steps become <see cref="ToolCall"/>/<see cref="ToolResult"/> events; off, only text and the conversation id remain.</summary>
    public bool Activity { get; init; } = true;

    /// <inheritdoc />
    public async IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var sessions = new SessionIds();
        HashSet<string> started = [];
        HashSet<string> finished = [];
        await foreach (var item in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
        {
            if (!item.Parsed || !item.Text.StartsWith('{') || item.Value is not JsonObject obj)
            {
                yield return new TextDelta(item.Text + "\n");
                continue;
            }

            var kind = Json.AsString(obj["event"]);
            IEnumerable<StreamEvent> pieces = kind switch
            {
                "step_update" => StepEvents(obj, started, finished),
                "init" => Conversation(sessions, obj["conversation_id"]),
                "result" => Conversation(sessions, Json.AsObject(obj["result"])["conversation_id"]),
                _ => [],
            };
            foreach (var piece in pieces) yield return piece;
        }
    }

    private static IEnumerable<StreamEvent> Conversation(SessionIds sessions, JsonNode? id)
    {
        var update = sessions.Dedupe(id);
        return update is null ? [] : [update];
    }

    private IEnumerable<StreamEvent> StepEvents(JsonObject obj, HashSet<string> started, HashSet<string> finished)
    {
        var step = Json.AsObject(obj["step_update"]);
        var type = Json.AsString(step["step_type"]);
        if (type == "agent_response")
        {
            return Json.AsString(step["text_delta"]) is { Length: > 0 } delta ? [new TextDelta(delta)] : [];
        }
        return Activity && type == "tool" ? ToolEvents(step, started, finished) : [];
    }

    /// <summary>Antigravity repeats a tool step as its state changes (ACTIVE to DONE).</summary>
    private static List<StreamEvent> ToolEvents(JsonObject step, HashSet<string> started, HashSet<string> finished)
    {
        var callId = PyStr(step["step_index"], "None");
        var info = Json.AsObject(step["tool_info"]);
        var events = new List<StreamEvent>();
        if (started.Add(callId))
        {
            var name = Json.IsTruthy(step["tool_name"]) ? PyStr(step["tool_name"], "") :
                Json.IsTruthy(info["name"]) ? PyStr(info["name"], "") : "tool";
            var parameters = info["parameters"];
            events.Add(new ToolCall(callId, name, Json.IsTruthy(parameters) ? parameters!.DeepClone() : new JsonObject()));
        }
        var state = Json.AsString(step["state"]);
        if (state is not null && ToolEndStates.Contains(state) && finished.Add(callId))
        {
            events.Add(new ToolResult(callId, Json.AsString(info["output"]) ?? "", state != "DONE"));
        }
        return events;
    }

    /// <summary>A JSON value the way Python's <c>str()</c> shows it for the scalars a step carries.</summary>
    private static string PyStr(JsonNode? value, string missing) => value switch
    {
        null => missing,
        JsonValue v when v.TryGetValue<string>(out var s) => s,
        JsonValue v when v.TryGetValue<bool>(out var b) => b ? "True" : "False",
        _ => value.ToJsonString(),
    };
}
