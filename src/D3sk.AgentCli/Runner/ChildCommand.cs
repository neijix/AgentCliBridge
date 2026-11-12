namespace D3sk.AgentCli.Runner;

/// <summary>What to start: a program, its arguments and the whole environment it gets.</summary>
/// <remarks>
/// The host owns the child environment: <see cref="Environment"/> replaces the parent's
/// completely and is required, so the runner can never fall back to the parent's variables.
/// </remarks>
public sealed record ChildCommand
{
    /// <summary>The program to start (a path or a name found on the child's <c>PATH</c>).</summary>
    public required string FileName { get; init; }

    /// <summary>Arguments, passed one by one (no shell, no quoting).</summary>
    public IReadOnlyList<string> Arguments { get; init; } = [];

    /// <summary>The working directory, or null for this process's.</summary>
    public string? WorkingDirectory { get; init; }

    /// <summary>The child's entire environment.</summary>
    public required IReadOnlyDictionary<string, string> Environment { get; init; }

    /// <summary>
    /// A prompt written to the child's stdin before it is closed (a prompt too long for the
    /// command line). Ignored when <see cref="LiveInput"/> is set.
    /// </summary>
    public string? StdinText { get; init; }

    /// <summary>Keeps stdin open for live messages; null closes stdin at once (the CLI never blocks on it).</summary>
    public ChildInput? LiveInput { get; init; }
}
