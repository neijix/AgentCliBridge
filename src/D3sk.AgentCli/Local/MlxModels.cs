namespace D3sk.AgentCli.Local;

/// <summary>The MLX weights downloaded on this computer, and what a local model is told.</summary>
public static class MlxModels
{
    private const string CachePrefix = "models--mlx-community--";

    /// <summary>
    /// The <c>mlx-community</c> model ids whose snapshot has a <c>config.json</c>, sorted. A half-finished
    /// download (a folder, no snapshot) is not offered: the server would fail to load it.
    /// </summary>
    public static IReadOnlyList<string> Installed(string? cache = null)
    {
        var root = cache ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".cache", "huggingface", "hub");
        var found = new List<string>();
        try
        {
            foreach (var folder in Directory.EnumerateDirectories(root))
            {
                var name = Path.GetFileName(folder);
                if (name.StartsWith(CachePrefix, StringComparison.Ordinal) && HasReadySnapshot(folder))
                {
                    var id = name["models--".Length..];
                    var dash = id.IndexOf("--", StringComparison.Ordinal);
                    found.Add(dash < 0 ? id : string.Concat(id.AsSpan(0, dash), "/", id.AsSpan(dash + 2)));
                }
            }
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return found.Count == 0 ? [] : [.. found.Order(StringComparer.Ordinal)];
        }

        return [.. found.Order(StringComparer.Ordinal)];
    }

    /// <summary>What the model is told: text only, which project the chat is about, then the host's closing rules.</summary>
    public static string SystemText(string cwd, string? projectName, IReadOnlyList<string> replyRules)
    {
        var name = string.IsNullOrEmpty(projectName) ? Path.GetFileName(cwd.TrimEnd('/', '\\')) : projectName;
        var lines = new List<string>
        {
            "You are a local model running on this computer (MLX). You have no tools: "
                + "you cannot read or edit files, run commands, or browse the web. Answer in text. "
                + "If the request needs those, say so in one sentence.",
            $"The chat is about the project '{name}' at {cwd}.",
        };
        lines.AddRange(replyRules);
        return string.Join('\n', lines);
    }

    /// <summary>The model id without its <c>mlx-community/</c> publisher, as the picker shows it.</summary>
    public static string Short(string model) =>
        model.StartsWith("mlx-community/", StringComparison.Ordinal) ? model["mlx-community/".Length..] : model;

    private static bool HasReadySnapshot(string folder)
    {
        var snapshots = Path.Combine(folder, "snapshots");
        try
        {
            return Directory.Exists(snapshots)
                && Directory.EnumerateDirectories(snapshots).Any(snap => File.Exists(Path.Combine(snap, "config.json")));
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }
}
