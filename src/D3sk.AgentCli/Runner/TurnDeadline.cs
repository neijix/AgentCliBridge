namespace D3sk.AgentCli.Runner;

/// <summary>
/// The deadline that starts when a CLI reports the end of its turn (its <c>result</c> event).
/// Before <see cref="Start"/> reads wait as long as the CLI works; after it they wait at most the
/// grace in total. A CLI that lingers, or a child it started that inherited our pipe, then cannot
/// leave the host's turn "working".
/// </summary>
public sealed class TurnDeadline
{
    /// <summary>The default grace after a turn's result (15 s).</summary>
    public static readonly TimeSpan DefaultGrace = TimeSpan.FromSeconds(15);

    private readonly object _gate = new();
    private DateTimeOffset? _deadline;

    /// <summary>Creates a deadline with the given grace.</summary>
    public TurnDeadline(TimeSpan grace) => Grace = grace;

    /// <summary>How long stdout may stay open once the turn ended.</summary>
    public TimeSpan Grace { get; }

    /// <summary>True once stdout was still open when the grace ran out.</summary>
    public bool Expired { get; internal set; }

    /// <summary>True once <see cref="Start"/> was called.</summary>
    public bool Started
    {
        get { lock (_gate) { return _deadline is not null; } }
    }

    /// <summary>The turn reported its end; the first call fixes the deadline.</summary>
    public void Start()
    {
        lock (_gate)
        {
            _deadline ??= DateTimeOffset.UtcNow + Grace;
        }
    }

    /// <summary>Time left, or null before <see cref="Start"/>.</summary>
    public TimeSpan? Remaining()
    {
        lock (_gate)
        {
            if (_deadline is null)
            {
                return null;
            }
            var left = _deadline.Value - DateTimeOffset.UtcNow;
            return left < TimeSpan.Zero ? TimeSpan.Zero : left;
        }
    }
}
