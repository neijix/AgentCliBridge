using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;

namespace D3sk.AgentCli.Output.Common;

/// <summary>The session id already emitted, so a repeat of it is not a second event. One per parsed turn.</summary>
public sealed class SessionIds
{
    private string? _seen;

    /// <summary>
    /// A <see cref="SessionUpdate"/> for a new id, or null when <paramref name="sid"/> is empty or
    /// already emitted. OpenCode only treats a string <c>sessionID</c> as an id
    /// (<paramref name="requireString"/>); the other CLIs emit whatever truthy id they sent, a
    /// number as its JSON text.
    /// </summary>
    public SessionUpdate? Dedupe(JsonNode? sid, bool requireString = false)
    {
        var text = Json.AsString(sid);
        if (requireString && text is null)
        {
            return null;
        }

        if (!Json.IsTruthy(sid))
        {
            return null;
        }

        text ??= sid!.ToJsonString();
        if (text == _seen)
        {
            return null;
        }

        _seen = text;
        return new SessionUpdate(text);
    }
}
