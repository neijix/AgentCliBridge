namespace D3sk.AgentCli.Login;

/// <summary>A sign-in command that is still waiting for the owner (it prints a link, then waits for a browser or a pasted code).</summary>
public interface ILoginProcess
{
    /// <summary>Whether the process has ended.</summary>
    bool HasExited { get; }

    /// <summary>The exit code once <see cref="HasExited"/>.</summary>
    int? ExitCode { get; }

    /// <summary>Whether stdin is open for a pasted code.</summary>
    bool CanWrite { get; }

    /// <summary>The merged stdout and stderr, line by line, until the process closes them.</summary>
    IAsyncEnumerable<string> ReadLinesAsync(CancellationToken ct);

    /// <summary>Writes to stdin and flushes; throws <see cref="IOException"/> when the process is gone.</summary>
    ValueTask WriteAsync(string text, CancellationToken ct);

    /// <summary>Asks the process (and what it started) to end.</summary>
    void Terminate();

    /// <summary>Ends the process for certain.</summary>
    void Kill();

    /// <summary>Waits up to <paramref name="timeout"/> for the process to end; true when it did.</summary>
    Task<bool> WaitForExitAsync(TimeSpan timeout, CancellationToken ct);
}

/// <summary>What a finished one-shot command printed.</summary>
public sealed record LoginCommandResult(int ExitCode, string Stdout, string Stderr);

/// <summary>Starts the CLIs; tests use a fake, the app uses <see cref="SystemLoginHost"/>.</summary>
public interface ILoginHost
{
    /// <summary>The host's own environment (what a CLI inherits).</summary>
    IReadOnlyDictionary<string, string> Environment { get; }

    /// <summary>Starts a sign-in command with <paramref name="envOverlay"/> on top of the host environment.</summary>
    ILoginProcess Start(IReadOnlyList<string> argv, IReadOnlyDictionary<string, string> envOverlay, bool keepStdin);

    /// <summary>Runs a short command (status, logout) with stdin closed; throws <see cref="IOException"/>, <see cref="TimeoutException"/> or a start failure when it cannot.</summary>
    Task<LoginCommandResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct);

    /// <summary>A download can arrive quarantined by macOS; launching it then is Gatekeeper's trash dialog. No-op elsewhere.</summary>
    void ClearQuarantine(string binary);
}
