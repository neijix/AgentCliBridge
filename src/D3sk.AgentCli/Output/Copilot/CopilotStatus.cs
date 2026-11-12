namespace D3sk.AgentCli.Output.Copilot;

/// <summary>
/// What the host reads once a Copilot stream ends: the process itself exits 0 even on failure, so the
/// <c>result</c> line's exit code is the authoritative one, and <c>session.error</c> carries the message.
/// The host owns one per turn and hands it to <see cref="CopilotParser"/>.
/// </summary>
public sealed class CopilotStatus
{
    /// <summary>The <c>exitCode</c> of the <c>result</c> line, or null when none arrived.</summary>
    public int? ResultExit { get; set; }

    /// <summary>The last <c>session.error</c> message, or null.</summary>
    public string? PendingError { get; set; }
}
