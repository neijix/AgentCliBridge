namespace D3sk.AgentCli.Install;

/// <summary>A native install to delete: a folder and the symlinks that point into it.</summary>
/// <param name="Dir">The install folder.</param>
/// <param name="Links">The symlinks to remove first.</param>
public sealed record RemoveTarget(string Dir, IReadOnlyList<string> Links);

/// <summary>
/// A vendor's install script, fetched to a file and run from there: never piped into a shell.
/// </summary>
/// <param name="Url">The https address of the script.</param>
/// <param name="FileName">The name it is saved under (<c>install.sh</c>, <c>install.ps1</c>).</param>
/// <param name="Interpreter">The argv that runs a file; the saved path is appended.</param>
/// <param name="ChecksumUrl">Where the vendor publishes the script's SHA-256, or null when it does not.</param>
public sealed record ScriptSource(string Url, string FileName, IReadOnlyList<string> Interpreter, string? ChecksumUrl = null);

/// <summary>
/// How to install, update or remove one CLI. The argv is always built here, never taken from a
/// request. An empty plan carries a <see cref="Hint"/> for the owner instead.
/// </summary>
public sealed record CliPlan
{
    /// <summary>The first command to run; empty when there is none.</summary>
    public IReadOnlyList<string> Argv { get; init; } = [];

    /// <summary>Commands to run, in order, after <see cref="Argv"/> succeeded.</summary>
    public IReadOnlyList<IReadOnlyList<string>> Then { get; init; } = [];

    /// <summary>Who does it: Homebrew, npm, WinGet, its own updater, its install script.</summary>
    public string How { get; init; } = "";

    /// <summary>The command line the owner can run by hand if the plan fails.</summary>
    public string Manual { get; init; } = "";

    /// <summary>What to do instead when the host cannot do it; set only on an empty plan.</summary>
    public string Hint { get; init; } = "";

    /// <summary>A script to download, check and run (replaces <see cref="Argv"/> as the first step).</summary>
    public ScriptSource? Script { get; init; }

    /// <summary>A native install to delete (uninstall only).</summary>
    public RemoveTarget? Remove { get; init; }

    /// <summary>Whether the host can carry this plan out.</summary>
    public bool Runnable => Argv.Count > 0 || Script is not null || Remove is not null;
}
