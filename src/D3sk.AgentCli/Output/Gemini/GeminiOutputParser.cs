using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Gemini;

/// <summary>
/// Gemini CLI's stdout. The bytes are Claude's stream-json with no cancel note of its own, so this
/// parser is <see cref="ClaudeOutputParser"/> without a <c>CancelledMessage</c>: it adds, drops and
/// reorders nothing.
/// </summary>
/// <param name="Activity">Whether thinking and tool events are shown, not only text.</param>
/// <param name="AfterResult">Started when a result ends the turn and no background agent is still working; null for none.</param>
public sealed record GeminiOutputParser(bool Activity = true, TurnDeadline? AfterResult = null) : IOutputParser
{
    /// <inheritdoc />
    public IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, CancellationToken cancellationToken = default) =>
        new ClaudeOutputParser(Activity, AfterResult).ParseAsync(lines, cancellationToken);
}
