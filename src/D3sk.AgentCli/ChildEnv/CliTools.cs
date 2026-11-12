namespace D3sk.AgentCli.ChildEnv;

/// <summary>
/// Windows helper tools (<c>winget</c>, <c>npm.cmd</c>) found by full path: a background process
/// starts with a bare PATH, and a bare name on a PATH is what another program can shadow.
/// </summary>
public static class CliTools
{
    private static readonly Dictionary<string, (string Variable, string Relative)[]> WindowsToolPlaces = new(StringComparer.Ordinal)
    {
        ["winget"] = [("LOCALAPPDATA", @"Microsoft\WindowsApps\winget.exe")],
        ["npm.cmd"] =
        [
            ("ProgramFiles", @"nodejs\npm.cmd"),
            ("ProgramFiles(x86)", @"nodejs\npm.cmd"),
            ("APPDATA", @"npm\npm.cmd"),
        ],
    };

    /// <summary>Whether <paramref name="path"/> is a file the current user may execute.</summary>
    public static bool IsExecutable(string path)
    {
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
        {
            return false;
        }
        if (OperatingSystem.IsWindows())
        {
            return true;
        }
        try
        {
            return (File.GetUnixFileMode(path) & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
        }
        catch (IOException)
        {
            return false;
        }
    }

    /// <summary>The first executable among <paramref name="paths"/>, or "".</summary>
    public static string FirstExecutable(IEnumerable<string> paths) => paths.FirstOrDefault(IsExecutable) ?? "";

    /// <summary>
    /// <c>shutil.which</c>: <paramref name="name"/> looked up in <paramref name="pathValue"/> (a
    /// PATH string; default the process PATH). On Windows PATHEXT extensions are tried too.
    /// </summary>
    public static string? Which(string name, string? pathValue = null, bool? isWindows = null)
    {
        var windows = isWindows ?? OperatingSystem.IsWindows();
        var separator = windows ? ';' : ':';
        var dirs = (pathValue ?? Environment.GetEnvironmentVariable("PATH") ?? "").Split(separator, StringSplitOptions.RemoveEmptyEntries);
        var names = new List<string> { name };
        if (windows)
        {
            var exts = (Environment.GetEnvironmentVariable("PATHEXT") ?? ".COM;.EXE;.BAT;.CMD").Split(';', StringSplitOptions.RemoveEmptyEntries);
            if (!exts.Any(e => name.EndsWith(e, StringComparison.OrdinalIgnoreCase)))
            {
                names.AddRange(exts.Select(e => name + e));
            }
        }
        if (name.Contains('/') || (windows && name.Contains('\\')))
        {
            return names.FirstOrDefault(IsExecutable);
        }
        foreach (var dir in dirs)
        {
            foreach (var candidate in names)
            {
                var full = Path.Combine(dir, candidate);
                if (IsExecutable(full))
                {
                    return full;
                }
            }
        }
        return null;
    }

    /// <summary>"<c>%variable%\relative</c>" when that variable is set: a Windows tool's fixed place.</summary>
    public static IReadOnlyList<string> WindowsPlaces(string variable, string relative, Func<string, string?>? env = null)
    {
        var root = (env ?? Environment.GetEnvironmentVariable)(variable) ?? "";
        return root.Length == 0 ? [] : [root.TrimEnd('\\', '/') + "\\" + relative.TrimStart('\\', '/')];
    }

    /// <summary>
    /// The full path of <c>winget</c> or <c>npm.cmd</c>; the bare <paramref name="name"/> when neither
    /// the PATH nor its usual folders have it (the run then fails with a clear "could not start").
    /// </summary>
    public static string WindowsTool(string name, Func<string, string?>? which = null, Func<IEnumerable<string>, string>? find = null, Func<string, string?>? env = null)
    {
        which ??= n => Which(n);
        find ??= FirstExecutable;
        var places = WindowsToolPlaces.GetValueOrDefault(name, [])
            .SelectMany(p => WindowsPlaces(p.Variable, p.Relative, env)).ToList();
        var found = which(name);
        if (!string.IsNullOrEmpty(found))
        {
            return found;
        }
        var place = find(places);
        return place.Length > 0 ? place : name;
    }
}
