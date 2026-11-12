using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Events;

/// <summary>A structured event the runner yields; the runner never formats transport frames.</summary>
public abstract record StreamEvent;

/// <summary>A chunk of assistant text, in arrival order.</summary>
public sealed record TextDelta(string Text) : StreamEvent;

/// <summary>The CLI's own session id, captured for resuming on later turns.</summary>
public sealed record SessionUpdate(string SessionId) : StreamEvent;

/// <summary>Terminal failure with a human-readable message.</summary>
public sealed record StreamError(string Message, string Code = "cli_agent_failed") : StreamEvent;

/// <summary>The subprocess exited; last event of a non-interrupted run.</summary>
public sealed record Completed(int ReturnCode) : StreamEvent;

/// <summary>A chunk of the model's visible reasoning, in arrival order.</summary>
public sealed record ThinkingDelta(string Text) : StreamEvent;

/// <summary>The agent started a tool; <paramref name="CallId"/> pairs it with its result.</summary>
public sealed record ToolCall(string CallId, string Name, JsonNode? Arguments) : StreamEvent;

/// <summary>
/// A display-only note for the person watching ("Loading the model…"): shown while the turn runs, never part of
/// the reply and never saved. <paramref name="Kind"/> names what it is about, for example <c>loading</c>.
/// </summary>
public sealed record Notice(string Text, string Kind = "") : StreamEvent;

/// <summary>A tool finished. <paramref name="Raw"/> is the CLI text before unwrapping, "" when nothing was unwrapped.</summary>
public sealed record ToolResult(string CallId, string Output, bool IsError = false, string Raw = "") : StreamEvent
{
    /// <summary>Equality ignores <see cref="Raw"/>, as the Python reference does.</summary>
    public bool Equals(ToolResult? other) =>
        other is not null && CallId == other.CallId && Output == other.Output && IsError == other.IsError;

    /// <inheritdoc />
    public override int GetHashCode() => HashCode.Combine(CallId, Output, IsError);
}

/// <summary>The CLI waits until the host allows or denies one tool call.</summary>
public sealed record ApprovalRequest(string RequestId, string CallId, string Name, JsonNode? Arguments, string Description = "") : StreamEvent;

/// <summary>The CLI took a message added with live input.</summary>
public sealed record InputAccepted(string Text) : StreamEvent;

/// <summary>The CLI answered a permission-mode change: it applies now, or <paramref name="Error"/> says why not.</summary>
public sealed record ModeChanged(string Mode, string Error = "") : StreamEvent;

/// <summary>A tool's output looks like a prompt injection; the turn is now tainted.</summary>
public sealed record InjectionDetected(string CallId, string ToolName, IReadOnlyList<string> Rules, string Excerpt, string DetailsUrl = "") : StreamEvent;

/// <summary>The guard denied a tool approval on a tainted turn.</summary>
public sealed record ActionBlocked(string RequestId, string CallId, string Name, JsonNode? Arguments, string Reason, string DetailsUrl = "") : StreamEvent;
