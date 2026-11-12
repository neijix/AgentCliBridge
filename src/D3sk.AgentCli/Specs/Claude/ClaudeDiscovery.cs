namespace D3sk.AgentCli.Specs.Claude;

/// <summary>Finds the Claude Code binary: the PATH first, then <c>~/.local/bin</c>.</summary>
public static class ClaudeDiscovery
{
    /// <summary>
    /// The first usable binary for <see cref="ClaudeSpec.Aliases"/>, or null. A dangling link or a
    /// non-executable file is not usable; an <c>.exe</c> twin is tried too.
    /// </summary>
    /// <param name="pathEnv">The PATH value; null reads the process environment.</param>
    /// <param name="home">The user's home folder; null reads the profile folder.</param>
    /// <param name="isUsable">Probe for an executable file; null checks the file system.</param>
    public static string? Resolve(string? pathEnv = null, string? home = null, Func<string, bool>? isUsable = null) =>
        ResolveAliases(ClaudeSpec.Aliases, pathEnv, home, isUsable);

    /// <summary>
    /// Resolves the first usable binary for <paramref name="aliases"/> on PATH (and optionally <c>~/.local/bin</c>).
    /// </summary>
    public static string? ResolveAliases(
        IReadOnlyList<string> aliases,
        string? pathEnv = null,
        string? home = null,
        Func<string, bool>? isUsable = null,
        bool includeLocalBin = true)
    {
        isUsable ??= IsUsableFile;
        pathEnv ??= Environment.GetEnvironmentVariable("PATH") ?? "";
        home ??= Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

        foreach (var alias in aliases)
        {
            foreach (var folder in pathEnv.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
            {
                var found = Probe(Path.Combine(folder, alias), isUsable);
                if (found is not null) return found;
            }
            if (includeLocalBin)
            {
                var local = Probe(Path.Combine(home, ".local", "bin", alias), isUsable);
                if (local is not null) return local;
            }
        }
        return null;
    }

    /// <summary>Returns <paramref name="path"/> (or <c>path + ".exe"</c>) when <paramref name="isUsable"/> accepts it.</summary>
    public static string? Probe(string path, Func<string, bool>? isUsable = null)
    {
        isUsable ??= IsUsableFile;
        if (isUsable(path)) return path;
        if (!path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) && isUsable(path + ".exe")) return path + ".exe";
        return null;
    }

    /// <summary>Whether <paramref name="path"/> points to an existing executable file (following symlinks).</summary>
    public static bool IsUsableFile(string path)
    {
        var info = new FileInfo(path);
        // File.Exists is true for a dangling link, so follow the link to its end.
        FileSystemInfo? target = info.LinkTarget is null ? info : info.ResolveLinkTarget(true);
        if (target is not { Exists: true } || target is DirectoryInfo) return false;
        if (OperatingSystem.IsWindows()) return true;
        return (File.GetUnixFileMode(target.FullName) & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
    }
}
