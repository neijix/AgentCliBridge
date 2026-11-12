using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Encodings.Web;

namespace D3sk.AgentCli.Events;

/// <summary>One named wire frame: <see cref="Data"/> always carries <c>"v"</c>.</summary>
public sealed record WireFrame(string Name, JsonObject Data);

/// <summary>
/// The chat wire format: events as named frames and the fold of frames into the parts a chat
/// message is stored as. AgentCli's own parts; the shared fixtures in tests/wire pin the fold.
/// Apps may add keys to a frame and their own frame names; the fold ignores names it does not know.
/// </summary>
public static class Wire
{
    /// <summary>The frame format version.</summary>
    public const int Version = 1;

    /// <summary>Characters of a tool's JSON-encoded arguments kept on the wire.</summary>
    public const int ArgumentsLimit = 8 * 1024;

    private static readonly HashSet<string> ToolCallOwnKeys = ["v", "type", "done", "call_id", "name", "arguments"];
    private static readonly HashSet<string> ToolResultOwnKeys = ["v", "type", "done", "call_id", "output", "is_error"];

    private static readonly JsonSerializerOptions Relaxed = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    private static string Cap(string text, int limit, out bool cut)
    {
        if (text.Length <= limit)
        {
            cut = false;
            return text;
        }
        cut = true;
        if (limit > 0 && char.IsHighSurrogate(text[limit - 1]))
        {
            limit--; // never split a surrogate pair
        }
        return text[..limit];
    }

    private static JsonNode? BoundArguments(JsonNode? arguments, out bool cut)
    {
        cut = false;
        if (arguments is null)
        {
            return null;
        }
        var encoded = arguments.ToJsonString(Relaxed);
        if (encoded.Length > ArgumentsLimit)
        {
            cut = true;
            return JsonValue.Create(Cap(encoded, ArgumentsLimit, out _));
        }
        return arguments.DeepClone();
    }

    /// <summary>
    /// The frame for a runner event. Free-text fields are cut at <paramref name="outputLimit"/>
    /// characters and tool arguments at <see cref="ArgumentsLimit"/>; when anything was cut the
    /// data gets <c>"truncated": true</c>.
    /// </summary>
    public static WireFrame ToWire(StreamEvent streamEvent, int outputLimit = 20000)
    {
        var data = new JsonObject { ["v"] = Version };
        var truncated = false;

        string Capped(string text)
        {
            var value = Cap(text, outputLimit, out var cut);
            truncated |= cut;
            return value;
        }

        JsonNode? Bounded(JsonNode? arguments)
        {
            var value = BoundArguments(arguments, out var cut);
            truncated |= cut;
            return value;
        }

        var name = PopulateFrame(streamEvent, data, Capped, Bounded);
        if (truncated)
        {
            data["truncated"] = true;
        }
        return new WireFrame(name, data);
    }

    private static string PopulateFrame(
        StreamEvent streamEvent,
        JsonObject data,
        Func<string, string> capped,
        Func<JsonNode?, JsonNode?> bounded)
    {
        switch (streamEvent)
        {
            case TextDelta e:
                data["text"] = e.Text;
                return "text";
            case ThinkingDelta e:
                data["text"] = e.Text;
                return "thinking";
            case ToolCall e:
                data["call_id"] = e.CallId;
                data["name"] = e.Name;
                data["arguments"] = bounded(e.Arguments);
                return "tool_call";
            case ToolResult e:
                data["call_id"] = e.CallId;
                data["output"] = capped(e.Output);
                data["is_error"] = e.IsError;
                return "tool_result";
            case ApprovalRequest e:
                data["approval_id"] = e.RequestId;
                data["call_id"] = e.CallId;
                data["name"] = e.Name;
                data["arguments"] = bounded(e.Arguments);
                data["description"] = capped(e.Description);
                return "approval_request";
            case InjectionDetected e:
                data["call_id"] = e.CallId;
                data["tool_name"] = e.ToolName;
                data["rules"] = new JsonArray(e.Rules.Select(rule => (JsonNode?)JsonValue.Create(rule)).ToArray());
                data["excerpt"] = capped(e.Excerpt);
                data["details_url"] = e.DetailsUrl;
                return "injection_detected";
            case ActionBlocked e:
                data["call_id"] = e.CallId;
                data["name"] = e.Name;
                data["reason"] = e.Reason;
                data["details_url"] = e.DetailsUrl;
                return "action_blocked";
            case InputAccepted:
                return "input_accepted";
            case ModeChanged e:
                data["mode"] = e.Mode;
                if (e.Error.Length > 0) data["error"] = capped(e.Error);
                return "permission_mode";
            case Notice e:
                data["message"] = capped(e.Text);
                if (e.Kind.Length > 0) data["notice_kind"] = e.Kind;
                return "notice";
            case SessionUpdate e:
                data["session_id"] = e.SessionId;
                return "session";
            case StreamError e:
                data["message"] = e.Message;
                data["code"] = e.Code;
                return "error";
            case Completed e:
                data["returncode"] = e.ReturnCode;
                return "done";
            default:
                throw new ArgumentException($"{streamEvent.GetType().Name} has no wire mapping: map it in Wire.ToWire", nameof(streamEvent));
        }
    }

    /// <summary>One Server-Sent-Events frame: <c>event: name</c> then <c>data: one-line ASCII JSON</c>.</summary>
    /// <exception cref="ArgumentException">The name holds a line break.</exception>
    public static string SseFrame(string name, JsonObject data)
    {
        if (name.Contains('\r') || name.Contains('\n'))
        {
            throw new ArgumentException($"SSE event name must not contain a line break: {name}", nameof(name));
        }
        return new StringBuilder("event: ").Append(name).Append("\ndata: ").Append(data.ToJsonString()).Append("\n\n").ToString();
    }

    private static string TextOf(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue<string>(out var text) ? text : node?.ToString() ?? "";

    /// <summary>
    /// Folds one frame into <paramref name="parts"/> (in place). Text/thinking runs merge; a
    /// <c>tool_call</c> appends a tool part and a <c>tool_result</c> completes the latest tool part
    /// with the same <c>call_id</c>, extra keys copied (a result's overriding the call's). Other
    /// frame names are ignored.
    /// </summary>
    public static void Fold(JsonArray parts, string name, JsonObject data)
    {
        switch (name)
        {
            case "text" or "thinking":
                var text = TextOf(data["text"]);
                if (parts.Count > 0 && parts[^1] is JsonObject last && TextOf(last["type"]) == name)
                {
                    last["text"] = TextOf(last["text"]) + text;
                }
                else
                {
                    parts.Add((JsonNode)new JsonObject { ["type"] = name, ["text"] = text });
                }
                break;
            case "tool_call":
                var part = new JsonObject
                {
                    ["type"] = "tool",
                    ["call_id"] = data["call_id"]?.DeepClone(),
                    ["name"] = data["name"]?.DeepClone(),
                    ["arguments"] = data["arguments"]?.DeepClone(),
                    ["output"] = "",
                    ["is_error"] = false,
                    ["done"] = false,
                };
                CopyExtras(data, part, ToolCallOwnKeys);
                parts.Add((JsonNode)part);
                break;
            case "tool_result":
                var callId = data["call_id"];
                for (var i = parts.Count - 1; i >= 0; i--)
                {
                    if (parts[i] is JsonObject tool && TextOf(tool["type"]) == "tool" && JsonNode.DeepEquals(tool["call_id"], callId))
                    {
                        tool["output"] = data["output"]?.DeepClone() ?? "";
                        tool["is_error"] = data["is_error"]?.DeepClone() ?? false;
                        tool["done"] = true;
                        CopyExtras(data, tool, ToolResultOwnKeys);
                        break;
                    }
                }
                break;
        }
    }

    private static void CopyExtras(JsonObject from, JsonObject to, HashSet<string> own)
    {
        foreach (var (key, value) in from)
        {
            if (!own.Contains(key))
            {
                to[key] = value?.DeepClone();
            }
        }
    }
}
