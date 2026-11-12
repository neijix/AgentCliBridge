using System.Runtime.CompilerServices;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Host;

/// <summary>
/// Splits the runner's events: the parser reads the lines, the pump keeps the errors and the exit
/// for the host. One enumerator, so the child is started once and stopped when the pump is disposed.
/// </summary>
internal sealed class TurnPump(IAsyncEnumerable<ChildEvent> source, CancellationToken ct) : IAsyncDisposable
{
    private IAsyncEnumerator<ChildEvent>? _events;

    /// <summary>Errors the runner reported, in order.</summary>
    public List<ChildError> Errors { get; } = [];

    /// <summary>How the child ended; null when it never started.</summary>
    public ChildExited? Exited { get; private set; }

    /// <summary>The stdout lines still to come, as the parser reads them.</summary>
    public async IAsyncEnumerable<ChildLine> LinesAsync([EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        _events ??= source.GetAsyncEnumerator(ct);
        while (await _events.MoveNextAsync().ConfigureAwait(false))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Take(_events.Current) is { } line)
            {
                yield return line;
            }
        }
    }

    /// <summary>Reads what is left once the parser stopped (the exit comes after the last line).</summary>
    public async Task DrainAsync()
    {
        await foreach (var _ in LinesAsync(ct).ConfigureAwait(false))
        {
            // lines after the parser stopped are dropped
        }
    }

    /// <inheritdoc />
    public ValueTask DisposeAsync() => _events?.DisposeAsync() ?? ValueTask.CompletedTask;

    private ChildLine? Take(ChildEvent e)
    {
        switch (e)
        {
            case ChildError error:
                Errors.Add(error);
                break;
            case ChildExited exited:
                Exited = exited;
                break;
        }
        return e as ChildLine;
    }
}
