namespace D3sk.AgentCli.ChildEnv;

/// <summary>A run was asked for without the environment its host must pass.</summary>
public sealed class MissingChildEnvironmentException : InvalidOperationException
{
    /// <summary>Creates the refusal.</summary>
    public MissingChildEnvironmentException()
        : base("the host passed no child environment; AgentCli never runs a CLI with the parent's environment") { }
}

/// <summary>
/// The environment a CLI child runs with. The host owns it: AgentCli takes the host's allowlist,
/// adds its own PATH shim folder and drops what would change the CLI's behavior. It never reads
/// the parent process's environment, and refuses a run when the host passed none.
/// </summary>
public static class ChildEnvironment
{
    /// <summary>
    /// Variable-name prefixes a <c>claude</c> child must not inherit: <c>CLAUDE_*</c> (which covers
    /// <c>CLAUDE_CODE_*</c>) and <c>AI_AGENT*</c> turn its transcript saving off.
    /// </summary>
    public static IReadOnlyList<string> TranscriptKillerPrefixes { get; } = ["CLAUDE_", "CLAUDE_CODE_", "AI_AGENT"];

    /// <summary>
    /// Builds the child environment from the host's <paramref name="allowlist"/>.
    /// </summary>
    /// <param name="allowlist">What the host passes; null or empty is refused.</param>
    /// <param name="shimFolder">Put first on PATH when set (the folder holds only shims).</param>
    /// <param name="dropPrefixes">Names starting with one of these (any case) are removed.</param>
    /// <param name="isWindows">Override of the OS check: names are then case-insensitive.</param>
    /// <exception cref="MissingChildEnvironmentException">The allowlist is null or empty.</exception>
    public static IReadOnlyDictionary<string, string> Build(
        IReadOnlyDictionary<string, string>? allowlist,
        string? shimFolder = null,
        IEnumerable<string>? dropPrefixes = null,
        bool? isWindows = null)
    {
        if (allowlist is null || allowlist.Count == 0)
        {
            throw new MissingChildEnvironmentException();
        }
        var windows = isWindows ?? OperatingSystem.IsWindows();
        var drops = (dropPrefixes ?? []).Where(p => p.Length > 0).ToArray();
        var result = new Dictionary<string, string>(windows ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
        foreach (var (name, value) in allowlist)
        {
            if (string.IsNullOrEmpty(name) || name.Contains('=') || value is null)
            {
                continue;
            }
            if (drops.Any(p => name.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }
            result[name] = value;
        }
        return string.IsNullOrEmpty(shimFolder) ? result : Shims.WithPath(result, shimFolder, windows);
    }
}
