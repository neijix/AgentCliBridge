using System.Text;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.ChildEnv;

/// <summary>
/// Launcher shims: a Python module on an agent CLI's PATH under a plain command name. The folder
/// holds only shims, so it can go first on the child's PATH. POSIX: <c>name</c> (a /bin/sh
/// script). Windows: <c>name.cmd</c> plus an extension-less sh launcher for Git Bash.
/// </summary>
public static partial class Shims
{
    /// <summary>The folder name below the per-user cache/app-data root.</summary>
    public const string AppFolder = "agent-cli-bridge";

    /// <summary>Environment variable that pins the shim folder.</summary>
    public const string ShimDirEnv = "AGENT_CLI_BRIDGE_SHIM_DIR";

    [GeneratedRegex(@"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    private static partial Regex SafeName();

    /// <summary>The per-user shim folder, from <paramref name="env"/> (default: the process environment).</summary>
    public static string DefaultFolder(Func<string, string?>? env = null, bool? isWindows = null)
    {
        env ??= Environment.GetEnvironmentVariable;
        var pinned = (env(ShimDirEnv) ?? "").Trim();
        if (pinned.Length > 0)
        {
            return ExpandHome(pinned);
        }
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (isWindows ?? OperatingSystem.IsWindows())
        {
            var local = (env("LOCALAPPDATA") ?? "").Trim();
            return Path.Combine(local.Length > 0 ? local : Path.Combine(home, "AppData", "Local"), AppFolder, "bin");
        }
        var cache = (env("XDG_CACHE_HOME") ?? "").Trim();
        return Path.Combine(cache.Length > 0 ? ExpandHome(cache) : Path.Combine(home, ".cache"), AppFolder, "bin");
    }

    private static string ExpandHome(string path) =>
        path == "~" || path.StartsWith("~/", StringComparison.Ordinal)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), path.TrimStart('~').TrimStart('/'))
            : path;

    private static void Check(string name, string module, string python)
    {
        if (!SafeName().IsMatch(name))
        {
            throw new ArgumentException($"unsafe shim name '{name}'");
        }
        if (!module.Split('.').All(part => SafeName().IsMatch(part)))
        {
            throw new ArgumentException($"unsafe module name '{module}'");
        }
        if (python.Length == 0 || python.IndexOfAny(['"', '\n', '\r', '\0']) >= 0)
        {
            throw new ArgumentException($"unusable python path '{python}'");
        }
    }

    private static string ShQuote(string path) => "\"" + Regex.Replace(path, @"([\\$`])", @"\$1") + "\"";

    /// <summary>The /bin/sh launcher.</summary>
    public static string PosixShim(string python, string module) => $"#!/bin/sh\nexec {ShQuote(python)} -m {module} \"$@\"\n";

    /// <summary>The cmd / PowerShell launcher (a literal % is written %%).</summary>
    public static string WindowsCmdShim(string python, string module) => $"@\"{python.Replace("%", "%%")}\" -m {module} %*\r\n";

    /// <summary>The Git Bash launcher (forward slashes avoid any backslash escaping question).</summary>
    public static string GitBashShim(string python, string module) => PosixShim(python.Replace('\\', '/'), module);

    /// <summary>File name to content of the launcher(s) written for this OS.</summary>
    public static IReadOnlyDictionary<string, string> ShimFiles(string name, string python, string module, bool isWindows)
    {
        Check(name, module, python);
        return isWindows
            ? new Dictionary<string, string> { [$"{name}.cmd"] = WindowsCmdShim(python, module), [name] = GitBashShim(python, module) }
            : new Dictionary<string, string> { [name] = PosixShim(python, module) };
    }

    private static bool WriteIfChanged(string path, string content, bool isWindows)
    {
        var data = new UTF8Encoding(false).GetBytes(content);
        const UnixFileMode Mode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
            | UnixFileMode.GroupRead | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute;
        try
        {
            if (File.ReadAllBytes(path).AsSpan().SequenceEqual(data) && (isWindows || OperatingSystem.IsWindows() || File.GetUnixFileMode(path) == Mode))
            {
                return false;
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        var tmp = Path.Combine(Path.GetDirectoryName(path)!, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllBytes(tmp, data);
            if (!isWindows && !OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(tmp, Mode);
            }
            File.Move(tmp, path, overwrite: true);
        }
        catch
        {
            try { File.Delete(tmp); } catch (IOException) { }
            throw;
        }
        return true;
    }

    /// <summary>
    /// Writes (or keeps) the <paramref name="name"/> launcher for <c>python -m module</c> and
    /// returns the shim folder. Each file is rewritten only when its content changes, atomically.
    /// </summary>
    /// <exception cref="ArgumentException">Unsafe name, module or python path.</exception>
    public static string EnsureShim(string name, string python, string module, string? folder = null, bool? isWindows = null)
    {
        var windows = isWindows ?? OperatingSystem.IsWindows();
        var target = folder ?? DefaultFolder(isWindows: windows);
        var files = ShimFiles(name, python, module, windows);
        Directory.CreateDirectory(target);
        foreach (var (fileName, content) in files)
        {
            WriteIfChanged(Path.Combine(target, fileName), content, windows);
        }
        return target;
    }

    /// <summary>The name the environment keeps PATH under: on Windows whatever its case.</summary>
    public static string PathKey(IEnumerable<string> names, bool isWindows) =>
        !isWindows ? "PATH" : names.FirstOrDefault(k => k.Equals("PATH", StringComparison.OrdinalIgnoreCase)) ?? "PATH";

    /// <summary>A copy of <paramref name="env"/> with <paramref name="folder"/> first on PATH (an earlier copy removed).</summary>
    public static Dictionary<string, string> WithPath(IReadOnlyDictionary<string, string> env, string folder, bool? isWindows = null)
    {
        var windows = isWindows ?? OperatingSystem.IsWindows();
        var result = new Dictionary<string, string>(env, windows ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
        var key = PathKey(result.Keys, windows);
        var separator = windows ? ';' : ':';
        var comparison = windows ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        var rest = (result.GetValueOrDefault(key, "")).Split(separator)
            .Where(p => p.Length > 0 && !p.Equals(folder, comparison));
        result[key] = string.Join(separator, rest.Prepend(folder));
        return result;
    }
}
