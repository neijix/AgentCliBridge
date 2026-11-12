using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Catalog;

/// <summary>
/// A composer's Effort and Ultracode choices turned into the CLI's own flags. Only Claude Code
/// (<c>--effort</c>, and the <c>ultracode</c> session setting) and Copilot CLI
/// (<c>--reasoning-effort</c>) take them; every other CLI gets nothing, and only a known level
/// ever reaches argv. A Claude model older than effort gets neither flag; a level it lacks runs
/// as the strongest one below it.
/// </summary>
public static partial class Effort
{
    /// <summary>Every level a page may send; "auto" (or anything unknown) passes no flag.</summary>
    public static readonly IReadOnlyList<string> All = ["auto", "low", "medium", "high", "xhigh", "max"];

    /// <summary>The levels Claude Code takes, weakest first.</summary>
    public static readonly IReadOnlyList<string> Claude = ["low", "medium", "high", "xhigh", "max"];

    /// <summary>The levels every Copilot model takes.</summary>
    public static readonly IReadOnlyList<string> Copilot = ["low", "medium", "high"];

    /// <summary>The session setting that switches Ultracode on, as the CLI's <c>--settings</c> value.</summary>
    public const string UltracodeSettings = "{\"ultracode\":true}";

    private static readonly Dictionary<string, string> ClaudeAliases = new(StringComparer.Ordinal)
    {
        ["opus"] = "claude-opus-5-5",
        ["sonnet"] = "claude-sonnet-5-5",
        ["haiku"] = "claude-haiku-5-5",
        ["fable"] = "claude-fable-5-1",
    };

    private static readonly Dictionary<string, string[]> ClaudeCaps = new(StringComparer.Ordinal)
    {
        ["claude-opus-4-5"] = ["low", "medium", "high"],
        ["claude-opus-4-6"] = ["low", "medium", "high", "max"],
        ["claude-sonnet-4-6"] = ["low", "medium", "high", "max"],
    };

    [GeneratedRegex(@"^claude-(3-|haiku-4|sonnet-4(-[05])?\z|opus-4(-[01])?\z|mythos-5\z)")]
    private static partial Regex NoEffortRx();

    [GeneratedRegex(@"^(?:[a-z]+\.)?anthropic\.")]
    private static partial Regex ProviderRx();

    [GeneratedRegex(@"-v\d+(?::\d+)?\z")]
    private static partial Regex VersionRx();

    [GeneratedRegex(@"[-@]\d{8}\z")]
    private static partial Regex DateRx();

    /// <summary>The table's id for a Claude model: lower case, without 1M tag, provider prefix, version or date.</summary>
    public static string ClaudeModelKey(string? model)
    {
        var text = (model ?? "").Trim().ToLowerInvariant();
        if (text.EndsWith("[1m]", StringComparison.Ordinal))
        {
            text = text[..^4];
        }
        text = text[(text.LastIndexOf('/') + 1)..];
        text = ProviderRx().Replace(text, "");
        text = VersionRx().Replace(text, "");
        text = DateRx().Replace(text, "");
        return ClaudeAliases.TryGetValue(text, out var full) ? full : text;
    }

    /// <summary>The levels this Claude model takes, or null when it takes no effort at all.</summary>
    public static IReadOnlyList<string>? ClaudeLevels(string? model)
    {
        var key = ClaudeModelKey(model);
        if (NoEffortRx().IsMatch(key))
        {
            return null;
        }
        return ClaudeCaps.TryGetValue(key, out var caps) ? caps : Claude;
    }

    /// <summary><paramref name="effort"/> when the model takes it, else the strongest level it takes below it.</summary>
    public static string Clamp(IReadOnlyList<string> levels, string effort)
    {
        if (levels.Contains(effort))
        {
            return effort;
        }
        var rank = Claude.ToList().IndexOf(effort);
        var below = levels.Where(l => Claude.ToList().IndexOf(l) <= rank).ToList();
        return below.Count > 0 ? below[^1] : levels[0];
    }

    /// <summary>The extra argv for this turn's effort and Ultracode on a CLI of <paramref name="flavor"/>, for <paramref name="model"/>.</summary>
    public static IReadOnlyList<string> Args(string flavor, string? effort = null, bool ultracode = false, string? model = null)
    {
        var args = new List<string>();
        if (flavor == "claude")
        {
            var levels = ClaudeLevels(model);
            if (levels is null)
            {
                return args;
            }
            if (effort is not null && Claude.Contains(effort))
            {
                args.AddRange(["--effort", Clamp(levels, effort)]);
            }
            if (ultracode && !ClaudeModelKey(model).Contains("haiku", StringComparison.Ordinal))
            {
                args.AddRange(["--settings", UltracodeSettings]);
            }
        }
        else if (flavor == "copilot" && effort is not null && Copilot.Contains(effort))
        {
            args.AddRange(["--reasoning-effort", effort]);
        }
        return args;
    }
}
