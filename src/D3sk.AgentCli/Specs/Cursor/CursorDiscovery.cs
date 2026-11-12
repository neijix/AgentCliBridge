using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Cursor;

/// <summary>Finds the Cursor Agent binary: the PATH, <c>~/.local/bin</c>, then the versioned installs.</summary>
public static class CursorDiscovery
{
    /// <summary>
    /// The first usable binary for <see cref="CursorSpec.Aliases"/>, or null. Each alias is tried on the
    /// PATH then in <c>~/.local/bin</c>; then <c>~/.local/share/cursor-agent/versions/&lt;ver&gt;/</c>,
    /// newest name first. A dangling link or a non-executable file is not usable; an <c>.exe</c> twin is tried too.
    /// </summary>
    public static string? Resolve(string? pathEnv = null, string? home = null, Func<string, bool>? isUsable = null)
    {
        var direct = ClaudeDiscovery.ResolveAliases(CursorSpec.Aliases, pathEnv, home, isUsable);
        if (direct is not null) return direct;

        home ??= Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var versions = Path.Combine(home, ".local", "share", "cursor-agent", "versions");
        if (!Directory.Exists(versions)) return null;
        var folders = Directory.GetDirectories(versions).OrderByDescending(Path.GetFileName, StringComparer.Ordinal);
        foreach (var folder in folders)
        {
            foreach (var name in CursorSpec.Aliases)
            {
                var found = ClaudeDiscovery.Probe(Path.Combine(folder, name), isUsable);
                if (found is not null) return found;
            }
        }
        return null;
    }

    /// <summary>
    /// Whether a <c>agent</c> or <c>cursor-agent</c> entry resolved into Grok CLI's own <c>.grok/bin</c>:
    /// that is Grok, and running it as Cursor would drive the wrong CLI. Either slash style, on any host OS.
    /// </summary>
    /// <param name="path">The entry's resolved binary path.</param>
    public static bool IsGrokCollision(string? path)
    {
        var parts = (path ?? "").Split(['/', '\\'], StringSplitOptions.RemoveEmptyEntries);
        for (var i = 0; i + 1 < parts.Length; i++)
        {
            if (parts[i].Equals(".grok", StringComparison.OrdinalIgnoreCase) && parts[i + 1].Equals("bin", StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }
}
