using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Grok;

/// <summary>Finds the Grok CLI binary on the PATH.</summary>
public static class GrokDiscovery
{
    /// <summary>The first usable binary for <see cref="GrokSpec.Aliases"/> on the PATH, or null; an <c>.exe</c> twin is tried too.</summary>
    /// <param name="pathEnv">The PATH value; null reads the process environment.</param>
    /// <param name="isUsable">Probe for an executable file; null checks the file system.</param>
    public static string? Resolve(string? pathEnv = null, Func<string, bool>? isUsable = null) =>
        ClaudeDiscovery.ResolveAliases(GrokSpec.Aliases, pathEnv, null, isUsable, includeLocalBin: false);
}
