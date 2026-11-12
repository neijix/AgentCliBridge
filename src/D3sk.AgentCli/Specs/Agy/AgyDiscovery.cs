using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Agy;

/// <summary>
/// Finds the Antigravity CLI: the PATH, then <c>~/.local/bin</c>, then the vendor layouts
/// (<c>~/.antigravity/Antigravity/bin</c> on macOS and Linux, <c>%LOCALAPPDATA%/agy/bin</c> on Windows).
/// </summary>
public static class AgyDiscovery
{
    /// <summary>
    /// The first usable binary, or null. A dangling link or a non-executable file is not usable; an
    /// <c>.exe</c> twin is tried too.
    /// </summary>
    public static string? Resolve(string? pathEnv = null, string? home = null, Func<string, bool>? isUsable = null, string? localAppData = null)
    {
        var direct = ClaudeDiscovery.ResolveAliases(AgySpec.Aliases, pathEnv, home, isUsable);
        if (direct is not null) return direct;

        home ??= Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (string.IsNullOrEmpty(localAppData)) localAppData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrEmpty(localAppData)) localAppData = Path.Combine(home, "AppData", "Local");

        return ClaudeDiscovery.Probe(Path.Combine(home, ".antigravity", "Antigravity", "bin", AgySpec.Command), isUsable)
            ?? ClaudeDiscovery.Probe(Path.Combine(localAppData, "agy", "bin", AgySpec.Command), isUsable);
    }
}
