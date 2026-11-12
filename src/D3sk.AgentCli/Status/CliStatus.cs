using System.Collections.Concurrent;
using System.ComponentModel;

namespace D3sk.AgentCli.Status;

/// <summary>An agent whose CLI is checked: its command, its display name and the binary discovery found ("" when none).</summary>
/// <param name="Command">The CLI's command name.</param>
/// <param name="Name">The name shown to the user (the command when empty).</param>
/// <param name="Path">The binary discovery found; it is the one probed.</param>
public sealed record AgentRef(string Command, string Name = "", string Path = "");

/// <summary>The installed version read from one CLI.</summary>
/// <param name="Version">The version, "" when unknown.</param>
/// <param name="Error">Why it is unknown, "" when it is not.</param>
public sealed record InstalledRow(string Version, string Error);

/// <summary>The newest version a release source names for one CLI.</summary>
/// <param name="Version">The version, "" when unknown.</param>
/// <param name="Source">anthropic, homebrew, npm or cursor; "" when the CLI has no query-only source.</param>
/// <param name="Error">Why it is unknown, "" when it is not.</param>
public sealed record LatestRow(string Version, string Source, string Error);

/// <summary>One agent's line in the chat foot and Settings › Agents.</summary>
/// <param name="Command">The CLI's command name.</param>
/// <param name="Name">The display name.</param>
/// <param name="Installed">The installed version, "" when unknown.</param>
/// <param name="Latest">The newest version, "" when unknown.</param>
/// <param name="IsOutdated"><c>true</c> when behind, <c>null</c> when either side is unknown.</param>
/// <param name="Source">Where the newest version came from.</param>
/// <param name="Error">The installed side's reason, else the newest side's; "" when both are known.</param>
/// <param name="CanSignIn">Whether Settings can sign this CLI in.</param>
/// <param name="NeedsCode">Whether that sign-in needs a pasted code.</param>
public sealed record CliStatusRow(
    string Command,
    string Name,
    string Installed,
    string Latest,
    bool? IsOutdated,
    string Source,
    string Error,
    bool CanSignIn,
    bool NeedsCode);

/// <summary>The rows of one check and when it ran.</summary>
/// <param name="CheckedAt">Seconds since the Unix epoch.</param>
/// <param name="Agents">One row per agent that has a command.</param>
public sealed record CliStatusReport(double CheckedAt, IReadOnlyList<CliStatusRow> Agents);

/// <summary>What <see cref="CliStatus"/> reads and when; every field defaults to the real thing.</summary>
public sealed record CliStatusSources
{
    /// <summary><c>&lt;cli&gt; --version</c> as text, given the command and its binary.</summary>
    public Func<string, string, CancellationToken, Task<string>>? RunVersion { get; init; }

    /// <summary>One GET of a release source.</summary>
    public Func<string, CancellationToken, Task<byte[]>>? Fetch { get; init; }

    /// <summary>The time, in seconds since the Unix epoch.</summary>
    public Func<double>? Clock { get; init; }

    /// <summary>Whether Settings can sign this command in; null uses the Login flows' table (<see cref="Login.LoginSpecs.CanSignIn"/>).</summary>
    public Func<string, bool>? CanSignIn { get; init; }

    /// <summary>Whether that sign-in needs a pasted code; null uses <see cref="Login.LoginSpecs.NeedsCode"/>.</summary>
    public Func<string, bool>? NeedsCode { get; init; }
}

/// <summary>
/// Installed against newest version of each agent CLI, cached per command: the installed version for
/// ten minutes (a <c>brew upgrade</c> shows up soon enough), the newest for an hour, a failure for
/// five — so a page asks on every chat switch without spawning a process or reaching the network each
/// time. Nothing here throws at the caller: a CLI that cannot run or a registry that does not answer
/// is a row with an empty version and its reason.
/// </summary>
public sealed class CliStatus
{
    /// <summary>How long a read installed version is kept.</summary>
    public const double InstalledTtl = 10 * 60.0;

    /// <summary>How long a read newest version is kept.</summary>
    public const double LatestTtl = 60 * 60.0;

    /// <summary>How long a failed read is kept before it is retried.</summary>
    public const double FailureTtl = 5 * 60.0;

    private readonly Func<string, string, CancellationToken, Task<string>> _runVersion;
    private readonly Func<double> _clock;
    private readonly Func<string, bool> _canSignIn;
    private readonly Func<string, bool> _needsCode;
    private readonly ConcurrentDictionary<string, (InstalledRow Row, double Expires)> _installed = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string> _paths = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<(string Command, string Url), (LatestRow Row, double Expires)> _latest = new();

    /// <summary>A checker over the real <c>--version</c> probe, release sources and clock, unless <paramref name="sources"/> gives others.</summary>
    public CliStatus(CliStatusSources? sources = null)
    {
        var probe = new VersionProbe();
        _runVersion = sources?.RunVersion ?? probe.RunAsync;
        Fetch = sources?.Fetch ?? ReleaseFetch.GetAsync;
        _clock = sources?.Clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
        _canSignIn = sources?.CanSignIn ?? Login.LoginSpecs.CanSignIn;
        _needsCode = sources?.NeedsCode ?? Login.LoginSpecs.NeedsCode;
    }

    /// <summary>The release-source reader these checks use (an update reads the same sources).</summary>
    public Func<string, CancellationToken, Task<byte[]>> Fetch { get; }

    /// <summary>Drops what is cached for <paramref name="command"/>: after an update its version is read again.</summary>
    public void Forget(string command)
    {
        _installed.TryRemove(command, out _);
        foreach (var key in _latest.Keys.Where(key => key.Command == command))
        {
            _latest.TryRemove(key, out _);
        }
    }

    /// <summary>The installed version of <paramref name="command"/>, from the cache unless it expired or <paramref name="force"/>.</summary>
    public async Task<InstalledRow> InstalledAsync(string command, bool force = false, string path = "", CancellationToken ct = default)
    {
        if (path.Length == 0 && _paths.TryGetValue(command, out var known))
        {
            path = known;
        }
        if (!force && _installed.TryGetValue(command, out var cached) && cached.Expires > _clock())
        {
            return cached.Row;
        }
        InstalledRow row;
        try
        {
            var version = ReleaseSources.ParseVersion(await _runVersion(command, path, ct).ConfigureAwait(false));
            row = new InstalledRow(version, version.Length > 0 ? "" : "no version in the output");
        }
        catch (Exception ex) when (IsProbeFailure(ex, ct))
        {
            row = new InstalledRow("", ex.Message);
        }
        _installed[command] = (row, _clock() + (row.Version.Length > 0 ? InstalledTtl : FailureTtl));
        return row;
    }

    /// <summary>The newest version of <paramref name="command"/> from its release source, cached apart per source.</summary>
    public async Task<LatestRow> LatestAsync(string command, bool force = false, string formula = "", bool isClaudeCask = false, CancellationToken ct = default)
    {
        var url = ReleaseSources.LatestUrl(command, formula, isClaudeCask);
        if (url.Length == 0)
        {
            return new LatestRow("", "", "");
        }
        if (!force && _latest.TryGetValue((command, url), out var cached) && cached.Expires > _clock())
        {
            return cached.Row;
        }
        var source = ReleaseSources.LatestSource(command, formula, isClaudeCask);
        LatestRow row;
        try
        {
            var version = ReleaseSources.ParseLatest(command, await Fetch(url, ct).ConfigureAwait(false), formula, isClaudeCask);
            row = new LatestRow(version, source, version.Length > 0 ? "" : "no version in the answer");
        }
        catch (Exception ex) when (IsProbeFailure(ex, ct))
        {
            row = new LatestRow("", source, ex.Message);
        }
        _latest[(command, url)] = (row, _clock() + (row.Version.Length > 0 ? LatestTtl : FailureTtl));
        return row;
    }

    /// <summary>One row per agent that has a command; <paramref name="force"/> re-checks now (the foot's click).</summary>
    public async Task<CliStatusReport> StatusAsync(IEnumerable<AgentRef> agents, bool force = false, CancellationToken ct = default)
    {
        var rows = new List<CliStatusRow>();
        foreach (var agent in agents.Where(agent => agent.Command.Length > 0))
        {
            var command = agent.Command;
            _paths[command] = agent.Path;
            var installed = await InstalledAsync(command, force, agent.Path, ct).ConfigureAwait(false);
            var resolved = agent.Path.Length > 0 && !OperatingSystem.IsWindows() ? RealPath(agent.Path) : "";
            var formula = ReleaseSources.HomebrewFormula(resolved);
            // A Claude cask can only reach the binary Anthropic serves for download: npm's `latest`
            // is often a few hours ahead of it, and comparing with npm offered an Update that cannot happen.
            var isCask = command == "claude" && ReleaseSources.IsClaudeCaskBinary(resolved);
            var latest = await LatestAsync(command, force, formula, isCask, ct).ConfigureAwait(false);
            rows.Add(new CliStatusRow(
                command,
                agent.Name.Length > 0 ? agent.Name : command,
                installed.Version,
                latest.Version,
                ReleaseSources.IsOutdated(installed.Version, latest.Version),
                latest.Source,
                installed.Error.Length > 0 ? installed.Error : latest.Error,
                _canSignIn(command),
                _needsCode(command)));
        }
        return new CliStatusReport(_clock(), rows);
    }

    /// <summary>The file a symlink finally points to (the link's own path when it is none).</summary>
    private static string RealPath(string path)
    {
        try
        {
            return File.ResolveLinkTarget(path, returnFinalTarget: true)?.FullName ?? Path.GetFullPath(path);
        }
        catch (IOException)
        {
            return "";
        }
    }

    // What a probe that cannot run, a registry that does not answer or an unreadable answer throws:
    // a row's reason. A caller's own cancellation and a bug propagate.
    private static bool IsProbeFailure(Exception ex, CancellationToken ct) =>
        !(ex is OperationCanceledException && ct.IsCancellationRequested)
        && ex is IOException or Win32Exception or TimeoutException or InvalidOperationException or FormatException
            or ArgumentException or HttpRequestException or OperationCanceledException;
}
