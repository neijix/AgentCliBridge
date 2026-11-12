using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Grok;

/// <summary>Grok CLI stdout: Claude's stream-json, plus Grok's own note when it cancels its turn.</summary>
public sealed class GrokOutputParser : IOutputParser
{
    /// <summary>The note for a result whose <c>stop_reason</c> is <c>cancelled</c>: a tool needed an approval a headless run cannot give.</summary>
    public const string CancelledMessage =
        "Grok cancelled its own turn: a tool needed an approval that a headless run cannot " +
        "give. Choose a more permissive mode (e.g. Bypass) if it should run that tool.";

    private static readonly ClaudeOutputParser Inner = new(CancelledMessage: CancelledMessage);

    /// <inheritdoc />
    public IAsyncEnumerable<StreamEvent> ParseAsync(IAsyncEnumerable<ChildLine> lines, CancellationToken cancellationToken = default) =>
        Inner.ParseAsync(lines, cancellationToken);
}
