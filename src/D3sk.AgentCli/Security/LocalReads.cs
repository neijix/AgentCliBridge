using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Security;

/// <summary>
/// Recognizes a tool call whose result is the local workspace (a file read, a search or edit in it, or a shell
/// command made only of local readers), not the web or another service. A finding in such a result is reported
/// and logged but neither taints nor stops the turn: the project's own code (a test fixture, a rule's pattern,
/// this guard's policy text) matches the rules all the time. Bytes a turn brought from outside and saved to disk
/// are the gap: once a call may have downloaded something (<see cref="MayDownload"/>), the guard stops exempting reads.
/// </summary>
internal static class LocalReads
{
    // Claude Code's file tools, then the other CLIs' recorded and documented names (tests/streams).
    private static readonly HashSet<string> FileTools = new(StringComparer.Ordinal)
    {
        "Read", "Grep", "Glob", "LS", "NotebookRead", "Edit", "MultiEdit", "Write", "NotebookEdit",
        "read", "read_file", "read_many_files", "view_file", "list_directory", "list_dir", "search_file_content",
    };

    private static readonly HashSet<string> ShellTools = new(StringComparer.Ordinal) { "Bash", "bash", "shell", "run_terminal_command" };

    // Commands that only read or print local files; none reaches the network or runs another command.
    private static readonly HashSet<string> Readers = new(StringComparer.Ordinal)
    {
        "cat", "head", "tail", "sed", "grep", "egrep", "fgrep", "rg", "ls", "wc", "sort", "uniq", "cut", "tr", "nl",
        "diff", "stat", "file", "tree", "jq", "cd", "pwd", "echo", "printf", "true", "basename", "dirname", "realpath", "find", "git",
    };

    private static readonly HashSet<string> GitReaders = new(StringComparer.Ordinal)
    {
        "log", "show", "diff", "status", "grep", "blame", "ls-files", "ls-tree", "cat-file", "rev-parse", "shortlog",
    };

    private static readonly HashSet<string> FindRunners = new(StringComparer.Ordinal) { "-exec", "-execdir", "-ok", "-okdir" };

    // Programs that bring outside content to disk (or print it), and git verbs that do.
    private static readonly HashSet<string> Downloaders = new(StringComparer.Ordinal)
    {
        "curl", "wget", "aria2c", "gh", "http", "https", "xh", "lynx", "w3m", "links", "ftp", "sftp", "scp", "rsync", "ssh", "nc", "ncat",
        "socat", "d3skwebscout", "Invoke-WebRequest", "Invoke-RestMethod", "iwr", "irm",
    };

    private static readonly HashSet<string> Wrappers = new(StringComparer.Ordinal)
    {
        "sudo", "doas", "env", "xargs", "timeout", "nohup", "nice", "command", "exec", "time", "watch", "stdbuf",
    };

    private static readonly HashSet<string> WrapperValueOptions = new(StringComparer.Ordinal)
    {
        "-u", "--unset", "-C", "--chdir", "-s", "--signal", "-k", "--kill-after", "-I", "-n", "-P", "-L", "-d", "-g", "-p", "-S",
    };

    private static readonly HashSet<string> Shells = new(StringComparer.Ordinal) { "sh", "bash", "zsh", "dash", "ksh", "fish" };

    private static readonly HashSet<string> GitDownloads = new(StringComparer.Ordinal) { "clone", "fetch", "pull", "submodule", "remote" };

    // A sed script made only of line addresses and print/delete/quit commands: no `e` (run), `w` (write) or `r`.
    private static readonly System.Text.RegularExpressions.Regex SedPrintScript = new(@"^[0-9,$~+ \t;!pPdDqQn=]*$", System.Text.RegularExpressions.RegexOptions.CultureInvariant);

    /// <summary>True when the call's result can only hold local workspace content.</summary>
    internal static bool IsLocal(ToolCall call) =>
        FileTools.Contains(call.Name) || (ShellLine(call) is { } command && IsLocalCommand(command));

    /// <summary>True when the call may have saved outside content on disk: a scout fetch, or a downloader run by a shell line.</summary>
    internal static bool MayDownload(ToolCall call)
    {
        if (ScoutCalls.IsFetchCall(call.Name, call.Arguments))
        {
            return true;
        }
        if (ShellLine(call) is { } command)
        {
            return RunsDownloader(command, depth: 0);
        }
        return ShellTools.Contains(call.Name); // a shell call whose command we cannot read
    }

    /// <summary>Every command of the line is a bare-named local reader; no substitution, subshell, socket or unparsable quoting.</summary>
    internal static bool IsLocalCommand(string command) =>
        !command.Contains("$(", StringComparison.Ordinal) && !command.Contains('`') && !IsNetworkPath(command)
        && Segments(command, out var isPlain) is { } segments && isPlain && segments.All(IsLocalSegment);

    /// <summary>A downloader in command position (after assignments and wrappers such as <c>sudo</c> or <c>xargs</c>), or in a <c>sh -c</c> script.</summary>
    private static bool RunsDownloader(string command, int depth)
    {
        if (depth > 3 || IsNetworkPath(command) || Segments(command.Replace('`', ';'), out _) is not { } segments)
        {
            return true;
        }
        if ((command.Contains('$') || command.Contains('`')) && segments.SelectMany(w => w).Any(w => Downloaders.Contains(Path.GetFileName(w.TrimStart('$', '(', '`')))))
        {
            return true; // `$(which curl) -so p URL`: the program is named only inside the substitution
        }
        return segments.Any(segment => SegmentRunsDownloader(segment, depth));
    }

    private static bool SegmentRunsDownloader(List<string> segment, int depth)
    {
        var i = CommandIndex(segment);
        if (i == segment.Count)
        {
            return false;
        }
        var name = Path.GetFileName(segment[i]);
        var rest = segment.Skip(i + 1).ToList();
        if (Downloaders.Contains(name) || (name == "git" && GitSubcommand(rest) is { } sub && GitDownloads.Contains(sub)))
        {
            return true;
        }
        var script = rest.SkipWhile(a => !(a.StartsWith('-') && !a.StartsWith("--", StringComparison.Ordinal) && a.Contains('c'))).Skip(1).FirstOrDefault();
        return Shells.Contains(name) && script is not null && RunsDownloader(script, depth + 1);
    }

    /// <summary>Index of the program word, past assignments, wrappers and their options.</summary>
    private static int CommandIndex(List<string> segment)
    {
        var i = 0;
        while (i < segment.Count && (IsAssignment(segment[i]) || Wrappers.Contains(segment[i]) || segment[i].StartsWith('-') || segment[i].All(char.IsDigit)))
        {
            i += WrapperValueOptions.Contains(segment[i]) ? 2 : 1; // `env -u HOME curl`: HOME is a value, not the command
        }
        return Math.Min(i, segment.Count);
    }

    /// <summary>The simple commands of a line, redirects and their targets dropped; null on unbalanced quotes.
    /// <paramref name="isPlain"/> is false when a subshell, a process substitution or a separator fused with a redirect (<c>;&lt;&gt;</c>) appears.</summary>
    private static List<List<string>>? Segments(string command, out bool isPlain)
    {
        isPlain = true;
        var words = ScoutCalls.Split(command.Replace('\r', '\n').Replace("\n", " ; ", StringComparison.Ordinal));
        if (words is null || words.Count == 0)
        {
            return words is null ? null : [];
        }
        var segments = new List<List<string>> { new() };
        for (var i = 0; i < words.Count; i++)
        {
            var word = words[i];
            if (!IsOperator(word))
            {
                segments[^1].Add(word);
                continue;
            }
            if (IsRedirect(word))
            {
                i++; // its target is a local path or a descriptor (sockets are refused by the callers)
                continue;
            }
            if (word.IndexOfAny(['(', ')', '<', '>']) >= 0)
            {
                isPlain = false;
            }
            segments.Add([]);
        }
        return segments;
    }

    private static bool IsAssignment(string word) => word.IndexOf('=') > 0 && !word.StartsWith('-');

    private static string? ShellLine(ToolCall call) =>
        ShellTools.Contains(call.Name) && call.Arguments is JsonObject args && args["command"] is JsonValue v && v.TryGetValue<string>(out var c) ? c : null;

    private static bool IsNetworkPath(string command) =>
        command.Contains("/dev/tcp", StringComparison.Ordinal) || command.Contains("/dev/udp", StringComparison.Ordinal);

    private static bool IsOperator(string word) => word.Length > 0 && word.All("();<>|&".Contains);

    private static bool IsRedirect(string word) => word.All("<>".Contains) || word is ">&" or "<&" or "&>" or "&>>";

    private static bool IsLocalSegment(List<string> words)
    {
        if (words.Count == 0)
        {
            return true; // `a ;; b`, a trailing `;`
        }
        var name = words[0];
        if (!Readers.Contains(name)) // a bare name only: `./tools/cat` may be anything
        {
            return false;
        }
        var args = words.Skip(1).ToList();
        return name switch
        {
            "git" => GitSubcommand(args) is { } sub && GitReaders.Contains(sub)
                && (sub != "grep" || !args.Any(a => a.StartsWith("-O", StringComparison.Ordinal) || a.StartsWith("--o", StringComparison.Ordinal))), // grep -O (--op…) runs a pager
            "find" => !args.Any(FindRunners.Contains),
            "rg" => !args.Any(a => a.StartsWith("--pre", StringComparison.Ordinal)), // --pre runs a command per file
            "sort" => !args.Any(a => a.StartsWith("--c", StringComparison.Ordinal)), // --compress-program (--co…) runs one
            "sed" => IsPrintOnlySed(args),
            _ => true,
        };
    }

    /// <summary>A sed call whose every script only prints or deletes lines; a script file is refused.</summary>
    private static bool IsPrintOnlySed(List<string> args)
    {
        var scripts = new List<string>();
        var hasExpression = false;
        var operands = new List<string>();
        for (var i = 0; i < args.Count; i++)
        {
            var arg = args[i];
            if (arg == "-e" || arg == "--expression")
            {
                hasExpression = true;
                scripts.Add(i + 1 < args.Count ? args[++i] : "e");
            }
            else if (arg.StartsWith("--expression=", StringComparison.Ordinal))
            {
                hasExpression = true;
                scripts.Add(arg["--expression=".Length..]);
            }
            else if (arg.StartsWith('-') && !IsPlainSedOption(arg))
            {
                return false; // a script file, a `-ne SCRIPT` bundle, or a long option sed may expand from an abbreviation
            }
            else if (!arg.StartsWith('-'))
            {
                operands.Add(arg);
            }
        }
        if (!hasExpression)
        {
            if (operands.Count == 0)
            {
                return false;
            }
            scripts.Add(operands[0]);
        }
        return scripts.All(SedPrintScript.IsMatch);
    }

    // sed expands any unique abbreviation of a long option (`--exp` is --expression), so only these exact forms pass.
    private static bool IsPlainSedOption(string arg) =>
        arg is "--quiet" or "--silent" or "--regexp-extended" or "--separate" or "--null-data" or "--unbuffered" or "--posix" or "--debug"
        || (!arg.StartsWith("--", StringComparison.Ordinal) && arg.Length > 1 && arg[1..].All("nEsrzu".Contains));

    /// <summary>The git subcommand after <c>-C dir</c> and flag options; null when there is none or a <c>-c</c> setting (a pager, a hook) could run a command.</summary>
    private static string? GitSubcommand(List<string> args)
    {
        for (var i = 0; i < args.Count; i++)
        {
            if (args[i].StartsWith("-c", StringComparison.Ordinal) || args[i].StartsWith("--config", StringComparison.Ordinal))
            {
                return null;
            }
            if (args[i] == "-C")
            {
                i++;
            }
            else if (!args[i].StartsWith('-'))
            {
                return args[i];
            }
        }
        return null;
    }
}
