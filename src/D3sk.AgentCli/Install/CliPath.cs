namespace D3sk.AgentCli.Install;

/// <summary>
/// A path as POSIX or Windows segments whatever this OS is, so plans for the other platform are
/// testable (Python's <c>PurePosixPath</c> / <c>PureWindowsPath</c>). The first segment of a rooted
/// path is its root (<c>/</c>, <c>C:\</c>).
/// </summary>
internal static class CliPath
{
    public static string[] Parts(string? path, bool windows)
    {
        if (string.IsNullOrEmpty(path))
        {
            return [];
        }
        var parts = new List<string>();
        if (windows)
        {
            var text = path.Replace('/', '\\');
            var segments = text.Split('\\', StringSplitOptions.RemoveEmptyEntries).ToList();
            if (segments.Count > 0 && segments[0].Length == 2 && segments[0][1] == ':')
            {
                parts.Add(segments[0] + "\\");
                segments.RemoveAt(0);
            }
            else if (text.StartsWith('\\'))
            {
                parts.Add("\\");
            }
            parts.AddRange(segments);
            return [.. parts];
        }
        if (path.StartsWith('/'))
        {
            parts.Add("/");
        }
        parts.AddRange(path.Split('/', StringSplitOptions.RemoveEmptyEntries));
        return [.. parts];
    }

    public static string Join(IEnumerable<string> parts, bool windows)
    {
        var separator = windows ? "\\" : "/";
        var text = "";
        foreach (var part in parts)
        {
            text = text.Length == 0 || text.EndsWith('/') || text.EndsWith('\\') ? text + part : text + separator + part;
        }
        return text;
    }

    public static string Parent(string path, bool windows)
    {
        var parts = Parts(path, windows);
        return Join(parts.Take(Math.Max(parts.Length - 1, 0)), windows);
    }

    public static bool IsUnder(string path, string folder)
    {
        var relative = Path.GetRelativePath(folder, path);
        return relative != "." && !relative.StartsWith("..", StringComparison.Ordinal) && !Path.IsPathRooted(relative);
    }
}
