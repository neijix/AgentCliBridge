using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Security;

/// <summary>One turn's view of the <see cref="SecurityLog"/>: remembers tool calls so a stop links to what they touched.</summary>
public sealed class TurnRecorder
{
    private static readonly string[] TargetKeys = ["query", "q", "file_path", "path", "command", "pattern"];

    private readonly SecurityLog _log;
    private readonly (string Key, string Value)[] _context;
    private readonly Dictionary<string, ToolCall> _calls = [];
    private string _taintedBy = "";

    internal TurnRecorder(SecurityLog log, string command, string model, string cwd)
    {
        _log = log;
        _context = [("command", command), ("model", model), ("cwd", cwd)];
    }

    /// <summary>Remembers tool calls; records a scout <c>fetch</c> that came back withheld.</summary>
    public void Observe(StreamEvent streamEvent)
    {
        if (streamEvent is ToolCall call)
        {
            _calls[call.CallId] = call;
            return;
        }
        if (streamEvent is not ToolResult result || !_calls.TryGetValue(result.CallId, out var known)
            || !ScoutCalls.IsFetchCall(known.Name, known.Arguments))
        {
            return;
        }
        var page = WithheldPage.Parse(result.Output);
        if (page is null && result.Raw.Length > 0)
        {
            page = WithheldPage.Parse(result.Raw);
        }
        if (page is null)
        {
            return;
        }
        var fields = CallFields(result.CallId);
        var entry = Entry(fields, SecurityLog.PageWithheldKind);
        entry["url"] = page.Url.Length > 0 ? page.Url : (string)fields["url"]!;
        entry["rules"] = new JsonArray($"injection_risk:{page.Risk}");
        entry["excerpt"] = string.Join('\n', page.Passages);
        _log.Record(entry);
    }

    /// <summary>Records a detection; the event again, with <c>DetailsUrl</c> when it was logged.</summary>
    public InjectionDetected Detected(InjectionDetected detection)
    {
        var fields = CallFields(detection.CallId, detection.ToolName);
        _taintedBy = _taintedBy.Length > 0 ? _taintedBy : (string)fields["url"]!;
        var entry = Entry(fields, SecurityLog.InjectionDetectedKind);
        entry["rules"] = new JsonArray(detection.Rules.Select(r => (JsonNode?)JsonValue.Create(r)).ToArray());
        entry["excerpt"] = SecurityText.Clip(detection.Excerpt);
        var id = _log.Record(entry);
        return id.Length > 0 ? detection with { DetailsUrl = SecurityLog.EntryUrl(id) } : detection;
    }

    /// <summary>Records a blocked action; the event again, with <c>DetailsUrl</c> when it was logged.</summary>
    public ActionBlocked Blocked(ActionBlocked blocked)
    {
        var entry = Entry(CallFields(blocked.CallId, blocked.Name, blocked.Arguments), SecurityLog.ActionBlockedKind);
        entry["rules"] = new JsonArray();
        entry["excerpt"] = "";
        entry["reason"] = blocked.Reason;
        entry["tainted_by"] = _taintedBy;
        var id = _log.Record(entry);
        return id.Length > 0 ? blocked with { DetailsUrl = SecurityLog.EntryUrl(id) } : blocked;
    }

    private JsonObject Entry(JsonObject fields, string kind)
    {
        var entry = new JsonObject();
        foreach (var (key, value) in _context)
        {
            entry[key] = value;
        }
        foreach (var (key, value) in fields)
        {
            entry[key] = value?.DeepClone();
        }
        entry["kind"] = kind;
        return entry;
    }

    private JsonObject CallFields(string callId, string name = "", JsonNode? arguments = null)
    {
        _calls.TryGetValue(callId, out var call);
        arguments ??= call?.Arguments;
        var url = SecurityText.FirstString(arguments, SecurityText.UrlKeys);
        if (url.Length == 0 && arguments is JsonObject obj)
        {
            url = ScoutCalls.FetchUrl(obj["command"] is JsonValue c && c.TryGetValue<string>(out var s) ? s : "");
        }
        return new JsonObject
        {
            ["tool"] = name.Length > 0 ? name : call?.Name ?? "tool",
            ["url"] = url,
            ["target"] = SecurityText.Clip(SecurityText.FirstString(arguments, TargetKeys), 300),
            ["arguments"] = arguments is null ? "" : SecurityText.Clip(arguments, 400),
        };
    }
}
