using D3sk.AgentCli.Events;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Common;

/// <summary>
/// One CLI's stdout turned into <see cref="StreamEvent"/>s. A parser reads only the runner's
/// <see cref="ChildLine"/>s (build them with <see cref="JsonLine.ReadAsync"/>); the host maps
/// <see cref="ChildError"/> and <see cref="ChildExited"/> to <see cref="StreamError"/> and
/// <see cref="Completed"/>. A line it cannot read is skipped, never thrown; its state (for example
/// a <see cref="SessionIds"/>) lives for one call, so a parser instance is reusable across turns.
/// </summary>
public interface IOutputParser
{
    /// <summary>Parses one turn's stdout lines, in arrival order, as they arrive.</summary>
    IAsyncEnumerable<StreamEvent> ParseAsync(IAsyncEnumerable<ChildLine> lines, CancellationToken cancellationToken = default);
}
