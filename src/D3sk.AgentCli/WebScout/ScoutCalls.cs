using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.WebScout;

/// <summary>
/// The one recognizer of a web-scout call among tool calls, shared by the turn policy and the security layer:
/// the shell command <c>d3skwebscout search|status|fetch</c> (or a leftover MCP server of that name).
/// Recognition only; the scout client lives elsewhere.
/// </summary>
internal static partial class ScoutCalls
{
    private const string Command = "d3skwebscout";
    private const string McpFetch = "mcp__d3skwebscout__fetch";
    private const string ShellTool = "Bash";
    private const string PunctuationChars = "();<>|&";
    private const string RiskyOption = "--allow-risky";
    private static readonly string[] FetchValueOptions = ["--offset", "--profile", "--human-action"];

    /// <summary>The command of a <c>Bash</c> tool call; null for another tool or a missing command.</summary>
    internal static string? ShellCommand(string name, JsonNode? arguments) =>
        name == ShellTool && arguments is JsonObject obj && obj["command"] is JsonValue v && v.TryGetValue<string>(out var c) ? c : null;

    /// <summary>True when the command text names the scout or its <c>--allow-risky</c> option, quotes and backslashes removed.</summary>
    internal static bool InvokesScout(string command)
    {
        var text = Quoting().Replace(command, "").ToLowerInvariant();
        return text.Contains("webscout", StringComparison.Ordinal) || text.Contains(RiskyOption[2..], StringComparison.Ordinal);
    }

    /// <summary>A tool call that reads a page through the scout (shell form, or a leftover MCP server).</summary>
    internal static bool IsFetchCall(string name, JsonNode? arguments)
    {
        if (name == McpFetch)
        {
            return true;
        }
        var words = Words(ShellCommand(name, arguments) ?? "");
        return words is { Count: >= 2 } && words[1] == "fetch";
    }

    /// <summary>The subcommand of exactly one plain scout call; null when the command is not one.</summary>
    internal static string? PlainVerb(string command) => Words(command) is { Count: >= 2 } words ? words[1] : null;

    /// <summary>Exactly one plain <c>d3skwebscout search …</c> without <c>--allow-risky</c>.</summary>
    internal static bool IsPlainSearch(string command) => IsPlain(command, "search", 2);

    /// <summary>Exactly one plain <c>d3skwebscout status</c> without <c>--allow-risky</c>.</summary>
    internal static bool IsPlainStatus(string command) => IsPlain(command, "status", 2);

    /// <summary>Exactly one plain <c>d3skwebscout fetch &lt;url&gt;</c> without <c>--allow-risky</c>.</summary>
    internal static bool IsPlainFetch(string command) => IsPlain(command, "fetch", 3);

    private static bool IsPlain(string command, string verb, int minimum) =>
        Words(command) is { } words && words.Count >= minimum && words[1] == verb && !words.Skip(2).Any(IsRiskyOption);

    // argparse takes any unambiguous prefix (--allow) and --allow-risky=...
    private static bool IsRiskyOption(string word)
    {
        var name = word.Split('=', 2)[0];
        return name.StartsWith("--a", StringComparison.Ordinal) && RiskyOption.StartsWith(name, StringComparison.Ordinal);
    }

    /// <summary>The url a plain scout fetch command reads; "" when it is not one.</summary>
    internal static string FetchUrl(string command)
    {
        var words = Words(command);
        if (words is not { Count: >= 3 } || words[1] != "fetch")
        {
            return "";
        }
        var skip = false;
        foreach (var word in words.Skip(2))
        {
            if (skip)
            {
                skip = false;
            }
            else if (FetchValueOptions.Contains(word))
            {
                skip = true;
            }
            else if (!word.StartsWith('-'))
            {
                return word;
            }
        }
        return "";
    }

    /// <summary>The words of a command that is one plain scout call; null otherwise (no <c>$</c>, backtick, line break, shell operator).</summary>
    internal static List<string>? Words(string command)
    {
        if (command.IndexOfAny(['$', '`', '\n', '\r']) >= 0)
        {
            return null;
        }
        var words = Split(command);
        if (words is null || words.Count == 0 || words[0] != Command)
        {
            return null;
        }
        return words.Any(w => w.Length > 0 && w.All(PunctuationChars.Contains)) ? null : words;
    }

    /// <summary>A POSIX shell word split (quotes, backslashes), with an operator run split off as its own word; null when quotes are unbalanced.</summary>
    private static List<string>? Split(string s)
    {
        var words = new List<string>();
        var cur = new StringBuilder();
        var inWord = false;
        void Flush()
        {
            if (inWord)
            {
                words.Add(cur.ToString());
            }
            cur.Clear();
            inWord = false;
        }
        for (var i = 0; i < s.Length; i++)
        {
            var ch = s[i];
            if (char.IsWhiteSpace(ch))
            {
                Flush();
            }
            else if (PunctuationChars.Contains(ch))
            {
                Flush();
                var j = i;
                while (j < s.Length && PunctuationChars.Contains(s[j]))
                {
                    j++;
                }
                words.Add(s[i..j]);
                i = j - 1;
            }
            else if (ch == '\\')
            {
                if (++i >= s.Length)
                {
                    return null;
                }
                cur.Append(s[i]);
                inWord = true;
            }
            else if (ch is '\'' or '"')
            {
                inWord = true;
                var end = Quoted(s, i, cur);
                if (end < 0)
                {
                    return null;
                }
                i = end;
            }
            else
            {
                cur.Append(ch);
                inWord = true;
            }
        }
        Flush();
        return words;
    }

    /// <summary>Appends the quoted text opening at <paramref name="open"/>; the index of the closing quote, or -1.</summary>
    private static int Quoted(string s, int open, StringBuilder cur)
    {
        var quote = s[open];
        for (var i = open + 1; i < s.Length; i++)
        {
            if (s[i] == quote)
            {
                return i;
            }
            if (quote == '"' && s[i] == '\\' && i + 1 < s.Length && s[i + 1] is '"' or '\\')
            {
                i++;
            }
            cur.Append(s[i]);
        }
        return -1;
    }

    [GeneratedRegex(@"[""'\\]")]
    private static partial Regex Quoting();
}
