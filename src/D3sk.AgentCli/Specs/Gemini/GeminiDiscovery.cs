using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Gemini;

/// <summary>Finds the Gemini CLI binary on the PATH, then <c>~/.local/bin</c>.</summary>
public static class GeminiDiscovery
{
    /// <summary>
    /// The first usable binary for <see cref="GeminiSpec.Aliases"/>, or null. A dangling link or a
    /// non-executable file is not usable; an <c>.exe</c> twin is tried too.
    /// </summary>
    /// <param name="pathEnv">The PATH value; null reads the process environment.</param>
    /// <param name="home">The user's home folder; null reads the profile folder.</param>
    /// <param name="isUsable">Probe for an executable file; null checks the file system.</param>
    public static string? Resolve(string? pathEnv = null, string? home = null, Func<string, bool>? isUsable = null) =>
        ClaudeDiscovery.ResolveAliases(GeminiSpec.Aliases, pathEnv, home, isUsable);
}
