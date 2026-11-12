using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Status;

/// <summary>Runs <c>&lt;cli&gt; --version</c> on a binary discovery already found.</summary>
public sealed class VersionProbe
{
    /// <summary>A Node-based CLI can take a couple of seconds to print its version.</summary>
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(20);

    private readonly Func<IReadOnlyList<string>, CancellationToken, Task<ProbeResult>> _run;
    private readonly Func<string, string?> _which;
    private readonly Func<string, bool> _clearQuarantine;
    private readonly bool _isWindows;

    /// <summary>The probe a machine uses: the real process runner, PATH lookup and quarantine clearing.</summary>
    public VersionProbe()
        : this((argv, ct) => ProbeProcess.RunAsync(argv, Timeout, ct), name => CliTools.Which(name), path => MacQuarantine.Clear(path), OperatingSystem.IsWindows())
    {
    }

    /// <summary>A probe with its three effects given (what the tests fake).</summary>
    /// <param name="run">Runs an argv and answers its output.</param>
    /// <param name="which">Finds a command on PATH, or null.</param>
    /// <param name="clearQuarantine">Drops macOS's download mark from a path.</param>
    /// <param name="isWindows">Whether a bare command is resolved to its full path (a <c>.cmd</c> shim).</param>
    public VersionProbe(
        Func<IReadOnlyList<string>, CancellationToken, Task<ProbeResult>> run,
        Func<string, string?> which,
        Func<string, bool> clearQuarantine,
        bool isWindows)
    {
        _run = run;
        _which = which;
        _clearQuarantine = clearQuarantine;
        _isWindows = isWindows;
    }

    /// <summary>
    /// The output of <c>--version</c> as text (stdout then stderr). <paramref name="path"/> is the binary
    /// discovery found: it is the one launched, never a second lookup. Throws on a missing or stuck binary.
    /// </summary>
    public async Task<string> RunAsync(string command, string path, CancellationToken ct)
    {
        var binary = path.Length > 0 ? path : (_isWindows ? _which(command) ?? command : command);
        // The first launch after a cask upgrade: the mark has to be gone before the binary starts.
        _clearQuarantine(path.Length > 0 ? path : _which(command) ?? binary);
        var done = await _run([binary, "--version"], ct).ConfigureAwait(false);
        return $"{done.Stdout}\n{done.Stderr}";
    }
}
