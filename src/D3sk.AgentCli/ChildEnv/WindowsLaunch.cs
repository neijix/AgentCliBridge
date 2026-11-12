using System.Text;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.ChildEnv;

/// <summary>A <c>.cmd</c> launcher this module cannot see through, with argv cmd.exe would rewrite.</summary>
public sealed class UnsafeLauncherException(string message) : ArgumentException(message);

/// <summary>What to start: the argv and what the swapped launcher would have set in the child's environment.</summary>
public sealed record LaunchPlan(IReadOnlyList<string> Argv, IReadOnlyDictionary<string, string> EnvOverlay);

/// <summary>
/// Windows: launch what a <c>.cmd</c> CLI launcher runs, never the launcher itself, so a turn's
/// argv (prompt text, JSON settings) is not re-parsed by cmd.exe. npm cmd-shims and Cursor
/// Agent's <c>agent.cmd</c> are seen through; any other launcher runs only when no argument holds
/// a character cmd.exe would act on.
/// </summary>
public static partial class WindowsLaunch
{
    private static readonly string[] LauncherSuffixes = [".cmd", ".bat"];

    /// <summary>Launchers that run launchers, followed this many levels.</summary>
    public const int MaxDepth = 4;

    /// <summary>Characters CreateProcess takes on a command line, its final NUL included.</summary>
    public const int CommandLineLimit = 32_767;

    /// <summary>Linux MAX_ARG_STRLEN: the most bytes one argument may take, its NUL included.</summary>
    public const int LinuxArgLimit = 131_072;

    [GeneratedRegex("[\"&|<>^%!()\\r\\n]")]
    private static partial Regex CmdSpecial();

    [GeneratedRegex("(?:^|&)\\s*@?((?:\"[^\"]*\"\\s*)+)%\\*\\s*$")]
    private static partial Regex RunLine();

    [GeneratedRegex("\"([^\"]*)\"")]
    private static partial Regex Quoted();

    [GeneratedRegex("SET\\s+\"_prog=([^\"]*)\"", RegexOptions.IgnoreCase)]
    private static partial Regex Prog();

    [GeneratedRegex("^([0-9]{4})\\.([0-9]{1,2})\\.([0-9]{1,2})(?:-([0-9]{2})-([0-9]{2})-([0-9]{2}))?-[a-f0-9]+$", RegexOptions.IgnoreCase)]
    private static partial Regex CursorVersion();

    /// <summary>Whether <paramref name="binary"/> is a batch launcher (CreateProcess hands <c>x.cmd.</c> and <c>x.cmd </c> to cmd.exe too).</summary>
    public static bool IsLauncher(string binary)
    {
        var trimmed = binary.TrimEnd(' ', '.');
        return LauncherSuffixes.Any(s => trimmed.EndsWith(s, StringComparison.OrdinalIgnoreCase));
    }

    private static string? Expand(string token, string folder)
    {
        foreach (var variable in new[] { "%dp0%", "%~dp0" })
        {
            if (token.StartsWith(variable, StringComparison.Ordinal))
            {
                // Split on both separators: off Windows a backslash is part of a file name.
                var parts = Regex.Split(token[variable.Length..], @"[\\/]").Where(p => p.Length > 0);
                token = string.Join(Path.DirectorySeparatorChar, parts.Prepend(folder.TrimEnd(Path.DirectorySeparatorChar)));
            }
        }
        return token.Contains('%') || token.Contains('!') ? null : token;
    }

    private static string? Interpreter(string text, string folder, Func<string, string?> which)
    {
        var names = Prog().Matches(text).Select(m => m.Groups[1].Value).ToList();
        foreach (var name in names)
        {
            var path = Expand(name, folder);
            if (path is not null && (path.Contains('\\') || path.Contains('/')) && File.Exists(path))
            {
                return path;
            }
        }
        for (var i = names.Count - 1; i >= 0; i--)
        {
            var name = names[i];
            if (name.Length > 0 && !name.Contains('%') && !name.Contains('\\') && !name.Contains('/'))
            {
                return which(name);
            }
        }
        return null;
    }

    /// <summary>
    /// The command an npm cmd-shim (or a one-line <c>@"&lt;exe&gt;" "&lt;script&gt;" %*</c> launcher)
    /// runs. <c>%dp0%</c> is the launcher's folder, <c>%_prog%</c> its interpreter. Null when a
    /// token still holds a variable or the program is missing.
    /// </summary>
    public static IReadOnlyList<string>? NpmShimArgv(string text, string folder, Func<string, string?>? which = null)
    {
        which ??= n => CliTools.Which(n);
        Match? match = null;
        foreach (var line in text.ReplaceLineEndings("\n").Split('\n').Reverse())
        {
            var m = RunLine().Match(line.Trim());
            if (m.Success)
            {
                match = m;
                break;
            }
        }
        if (match is null)
        {
            return null;
        }
        var argv = new List<string>();
        foreach (Match token in Quoted().Matches(match.Groups[1].Value))
        {
            var value = token.Groups[1].Value;
            var resolved = value == "%_prog%" ? Interpreter(text, folder, which) : Expand(value, folder);
            if (string.IsNullOrEmpty(resolved))
            {
                return null;
            }
            argv.Add(resolved);
        }
        return argv.Count == 0 || !File.Exists(argv[0]) ? null : argv;
    }

    private static int[]? CursorVersionKey(string name)
    {
        var m = CursorVersion().Match(name);
        return m.Success ? m.Groups.Cast<Group>().Skip(1).Select(g => g.Success ? int.Parse(g.Value) : 0).ToArray() : null;
    }

    /// <summary>
    /// Cursor Agent's <c>agent.cmd</c> / <c>cursor-agent.cmd</c>: the <c>node.exe index.js</c> its
    /// <c>cursor-agent.ps1</c> would run (beside it, else the newest complete <c>versions\&lt;version&gt;</c>).
    /// </summary>
    public static IReadOnlyList<string>? CursorAgentArgv(string launcher)
    {
        var folder = Path.GetDirectoryName(launcher) ?? "";
        if (!File.Exists(Path.Combine(folder, "cursor-agent.ps1")))
        {
            return null;
        }
        var candidates = new List<string> { folder };
        var versions = Path.Combine(folder, "versions");
        if (Directory.Exists(versions))
        {
            candidates.AddRange(Directory.EnumerateDirectories(versions)
                .Select(p => (Key: CursorVersionKey(Path.GetFileName(p)), Path: p))
                .Where(x => x.Key is not null)
                .OrderByDescending(x => x.Key, Comparer<int[]?>.Create((a, b) => a!.Zip(b!, (l, r) => l.CompareTo(r)).FirstOrDefault(c => c != 0)))
                .ThenByDescending(x => x.Path, StringComparer.Ordinal)
                .Select(x => x.Path));
        }
        foreach (var candidate in candidates)
        {
            var node = Path.Combine(candidate, "node.exe");
            var script = Path.Combine(candidate, "index.js");
            if (File.Exists(node) && File.Exists(script))
            {
                return [node, script];
            }
        }
        return null;
    }

    private static string? EnvGet(IReadOnlyDictionary<string, string> env, string name) =>
        env.FirstOrDefault(kv => kv.Key.Equals(name, StringComparison.OrdinalIgnoreCase)).Value;

    private static (IReadOnlyList<string> Argv, Dictionary<string, string> Env)? Resolve(string launcher, IReadOnlyDictionary<string, string> env)
    {
        var cursor = CursorAgentArgv(launcher);
        if (cursor is not null)
        {
            var overlay = new Dictionary<string, string> { ["CURSOR_INVOKED_AS"] = Path.GetFileName(launcher) }; // agent.cmd sets it unconditionally
            var localApp = EnvGet(env, "LOCALAPPDATA");
            if (!string.IsNullOrEmpty(localApp) && string.IsNullOrEmpty(EnvGet(env, "NODE_COMPILE_CACHE")))
            {
                overlay["NODE_COMPILE_CACHE"] = localApp.TrimEnd('\\', '/') + Path.DirectorySeparatorChar + "cursor-compile-cache";
            }
            return (cursor, overlay);
        }
        var text = File.ReadAllText(launcher, Encoding.UTF8);
        var path = EnvGet(env, "PATH");
        var target = NpmShimArgv(text, Path.GetDirectoryName(launcher) ?? "", n => CliTools.Which(n, path));
        return target is null ? null : (target, new Dictionary<string, string>());
    }

    /// <summary>
    /// <paramref name="argv"/> with a <c>.cmd</c> / <c>.bat</c> launcher swapped for the command it
    /// runs, plus what that launcher would have set in <paramref name="env"/> (the child's
    /// environment). Unchanged off Windows and for real executables.
    /// </summary>
    /// <exception cref="UnsafeLauncherException">A launcher it cannot see through and an argument cmd.exe would act on.</exception>
    public static LaunchPlan DirectLaunch(IReadOnlyList<string> argv, IReadOnlyDictionary<string, string>? env = null, bool? isWindows = null)
    {
        var windows = isWindows ?? OperatingSystem.IsWindows();
        var childEnv = env ?? new Dictionary<string, string>();
        var current = argv.ToList();
        var overlay = new Dictionary<string, string>();
        for (var i = 0; i < MaxDepth; i++)
        {
            if (!windows || current.Count == 0 || !IsLauncher(current[0]))
            {
                return new LaunchPlan(current, overlay);
            }
            (IReadOnlyList<string> Argv, Dictionary<string, string> Env)? resolved;
            try
            {
                var merged = new Dictionary<string, string>(childEnv, StringComparer.OrdinalIgnoreCase);
                foreach (var (k, v) in overlay)
                {
                    merged[k] = v;
                }
                resolved = Resolve(current[0], merged);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                resolved = null;
            }
            if (resolved is null)
            {
                break;
            }
            current = [.. resolved.Value.Argv, .. current.Skip(1)];
            foreach (var (k, v) in resolved.Value.Env)
            {
                overlay[k] = v;
            }
        }
        if (!IsLauncher(current[0]))
        {
            return new LaunchPlan(current, overlay);
        }
        if (current.Skip(1).Any(a => CmdSpecial().IsMatch(a)))
        {
            throw new UnsafeLauncherException(
                $"{Path.GetFileName(current[0])} is a Windows batch launcher, and cmd.exe would rewrite this turn's arguments "
                + "(quotes, & | < > ^ % ! ( ), line breaks). Point the bridge at the program it runs instead (the binary= setting or PATH).");
        }
        return new LaunchPlan(current, overlay);
    }

    /// <summary>One argument quoted as <c>subprocess.list2cmdline</c> does (the C runtime's rules).</summary>
    private static void QuoteArg(StringBuilder sb, string arg)
    {
        var needQuote = arg.Length == 0 || arg.Contains(' ') || arg.Contains('\t');
        if (needQuote)
        {
            sb.Append('"');
        }
        var backslashes = 0;
        foreach (var c in arg)
        {
            if (c == '\\')
            {
                backslashes++;
            }
            else if (c == '"')
            {
                sb.Append('\\', backslashes * 2 + 1).Append('"');
                backslashes = 0;
            }
            else
            {
                sb.Append('\\', backslashes).Append(c);
                backslashes = 0;
            }
        }
        sb.Append('\\', backslashes);
        if (needQuote)
        {
            sb.Append('\\', backslashes).Append('"');
        }
    }

    /// <summary>UTF-16 units <paramref name="argv"/> takes on a Windows command line; 0 off Windows (no such limit).</summary>
    public static int CommandLineLength(IReadOnlyList<string> argv, bool? isWindows = null)
    {
        if (!(isWindows ?? OperatingSystem.IsWindows()))
        {
            return 0;
        }
        var sb = new StringBuilder();
        for (var i = 0; i < argv.Count; i++)
        {
            if (i > 0)
            {
                sb.Append(' ');
            }
            QuoteArg(sb, argv[i]);
        }
        return sb.Length + 1; // string.Length counts UTF-16 units (an emoji counts 2); +1 for the final NUL
    }

    /// <summary>
    /// Whether the OS would refuse to start <paramref name="argv"/>: Windows, its command line is
    /// over <see cref="CommandLineLimit"/>; Linux, one argument reaches <see cref="LinuxArgLimit"/> bytes.
    /// </summary>
    public static bool IsTooLong(IReadOnlyList<string> argv, bool? isWindows = null, bool? isLinux = null)
    {
        if (CommandLineLength(argv, isWindows) > CommandLineLimit)
        {
            return true;
        }
        return (isLinux ?? OperatingSystem.IsLinux()) && argv.Any(a => Encoding.UTF8.GetByteCount(a) >= LinuxArgLimit);
    }
}
