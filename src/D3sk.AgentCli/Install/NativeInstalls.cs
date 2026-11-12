namespace D3sk.AgentCli.Install;

/// <summary>
/// A CLI that installed itself: Claude's and Cursor's native installers keep one folder under
/// <c>~/.local/share</c> with symlinks in <c>~/.local/bin</c>; Grok's puts its binaries in
/// <c>~/.grok/bin</c> beside its config and sign-in, so only that bin folder goes.
/// </summary>
public static class NativeInstalls
{
    private static readonly Dictionary<string, string> NativeDirs = new(StringComparer.Ordinal)
    {
        ["claude"] = "claude",
        ["agent"] = "cursor-agent",
        ["cursor-agent"] = "cursor-agent",
    };

    private static readonly Dictionary<string, string[]> OwnBinDirs = new(StringComparer.Ordinal)
    {
        ["grok"] = [".grok", "bin"],
    };

    /// <summary>The folder of a CLI whose installer owns a whole <c>bin</c> folder, or null.</summary>
    public static RemoveTarget? OwnBinInstall(string command, string resolved, string home)
    {
        if (!OwnBinDirs.TryGetValue(command, out var sub) || resolved.Length == 0)
        {
            return null;
        }
        var binDir = Path.Combine([home, .. sub]);
        if (!CliPath.IsUnder(resolved, binDir) || IsLink(binDir) || !Directory.Exists(binDir))
        {
            return null;
        }
        return new RemoveTarget(binDir, []);
    }

    /// <summary>The folder and links of a self-installed Claude or Cursor CLI under <paramref name="home"/>, or null.</summary>
    public static RemoveTarget? SelfInstalled(string command, string binary, string resolved, string home)
    {
        if (!NativeDirs.TryGetValue(command, out var folder) || binary.Length == 0 || resolved.Length == 0)
        {
            return null;
        }
        var share = Path.Combine(home, ".local", "share", folder);
        var binDir = Path.Combine(home, ".local", "bin");
        if (!CliPath.IsUnder(resolved, share) || Path.GetDirectoryName(binary) != binDir || IsLink(share) || !Directory.Exists(share))
        {
            return null;
        }
        var links = new List<string>();
        foreach (var name in folder == "claude" ? new[] { "claude" } : ["agent", "cursor-agent"])
        {
            var link = Path.Combine(binDir, name);
            // Another CLI's link with the same name is never removed.
            if (IsLink(link) && Resolve(link) is { } target && CliPath.IsUnder(target, share))
            {
                links.Add(link);
            }
        }
        return new RemoveTarget(share, links);
    }

    /// <summary>Delete what an uninstall plan named: its links, then its folder. Never follows a symlinked folder.</summary>
    public static InstallOutcome Remove(RemoveTarget target)
    {
        var lines = new List<string>();
        try
        {
            foreach (var link in target.Links.Where(IsLink))
            {
                File.Delete(link);
                lines.Add($"Removed {link}");
            }
            if (target.Dir.Length > 0 && Directory.Exists(target.Dir) && !IsLink(target.Dir))
            {
                Directory.Delete(target.Dir, recursive: true);
                lines.Add($"Removed {target.Dir}");
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            lines.Add(ex.Message);
            return InstallOutcome.Failed("remove", $"could not remove it: {ex.Message}", string.Join('\n', lines));
        }
        return InstallOutcome.Succeeded(string.Join('\n', lines));
    }

    private static bool IsLink(string path) => new FileInfo(path).LinkTarget is not null || new DirectoryInfo(path).LinkTarget is not null;

    private static string? Resolve(string link)
    {
        try
        {
            return (new FileInfo(link).ResolveLinkTarget(returnFinalTarget: true) as FileSystemInfo)?.FullName;
        }
        catch (IOException)
        {
            return null;
        }
    }
}
