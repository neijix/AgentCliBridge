using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Status;

/// <summary>
/// Where each CLI's newest version is published and how to read it: the npm registry's <c>latest</c>
/// dist-tag, Cursor's install script, Homebrew's formula API for a Homebrew formula, and
/// Anthropic's download for a Claude cask. Pure functions, no I/O.
/// </summary>
public static partial class ReleaseSources
{
    /// <summary>The npm registry the dist-tags are read from.</summary>
    public const string NpmRegistry = "https://registry.npmjs.org";

    /// <summary>Cursor's install script; it names the build it would download.</summary>
    public const string CursorInstallUrl = "https://cursor.com/install";

    /// <summary>Homebrew's formula API: what <c>brew upgrade</c> can actually deliver.</summary>
    public const string HomebrewFormulaApi = "https://formulae.brew.sh/api/formula";

    /// <summary>The newest Claude Code binary Anthropic serves for download (a cask can reach no newer one).</summary>
    public const string ClaudeReleaseLatestUrl = "https://downloads.claude.ai/claude-code-releases/latest";

    /// <summary>The Homebrew cask that follows Anthropic's latest download.</summary>
    public const string ClaudeLatestCask = "claude-code@latest";

    /// <summary>The npm package each npm-published CLI comes from.</summary>
    public static readonly IReadOnlyDictionary<string, string> NpmPackages = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["claude"] = "@anthropic-ai/claude-code",
        ["gemini"] = "@google/gemini-cli",
        ["copilot"] = "@github/copilot",
        ["grok"] = "@xai-official/grok",
        ["opencode"] = "opencode-ai",
    };

    /// <summary>The command names of Cursor's agent.</summary>
    public static readonly IReadOnlyList<string> CursorCommands = ["agent", "cursor-agent"];

    /// <summary>The cask names whose <c>claude</c> file is Claude Code (stable and <c>@latest</c>).</summary>
    private static readonly string[] ClaudeCasks = ["claude-code", ClaudeLatestCask];

    [GeneratedRegex(@"([0-9]+(?:\.[0-9]+)+)(-[0-9A-Za-z.]+)?")]
    private static partial Regex VersionPattern();

    [GeneratedRegex(@"downloads\.cursor\.com/lab/([0-9][0-9A-Za-z.-]*)/")]
    private static partial Regex CursorBuildPattern();

    [GeneratedRegex(@"^[a-z0-9][a-z0-9+._@-]*\z")]
    private static partial Regex FormulaPattern();

    [GeneratedRegex(@"^[0-9]+(?:\.[0-9]+)+\z")]
    private static partial Regex PlainVersionPattern();

    /// <summary>
    /// The first version-looking token of a <c>--version</c> output: <c>2.1.280 (Claude Code)</c> gives
    /// <c>2.1.280</c>; <c>2026.09.18-9a7762b</c> (Cursor) keeps its build suffix. "" when there is none.
    /// </summary>
    public static string ParseVersion(string? text)
    {
        var match = VersionPattern().Match(text ?? "");
        return match.Success ? match.Groups[1].Value + match.Groups[2].Value : "";
    }

    /// <summary>The dotted numeric part, what "newer" compares (<c>2.1.9</c> is below <c>2.1.10</c>); empty when unreadable.</summary>
    public static IReadOnlyList<BigInteger> VersionKey(string? version)
    {
        var match = VersionPattern().Match((version ?? "").Trim());
        return match.Success && match.Index == 0
            ? match.Groups[1].Value.Split('.').Select(BigInteger.Parse).ToArray()
            : [];
    }

    /// <summary><c>true</c> when the newest release is newer; <c>null</c> when either side is unknown.</summary>
    public static bool? IsOutdated(string? installed, string? latest)
    {
        var here = VersionKey(installed);
        var there = VersionKey(latest);
        if (here.Count == 0 || there.Count == 0)
        {
            return null;
        }
        for (var i = 0; i < Math.Min(here.Count, there.Count); i++)
        {
            var order = there[i].CompareTo(here[i]);
            if (order != 0)
            {
                return order > 0;
            }
        }
        return there.Count > here.Count;
    }

    /// <summary>The Homebrew formula a binary belongs to (<c>.../Cellar/&lt;formula&gt;/&lt;version&gt;/...</c>), else "".</summary>
    public static string HomebrewFormula(string? resolved)
    {
        var parts = Segments(resolved);
        var at = Array.IndexOf(parts, "Cellar");
        if (at < 0 || at + 1 >= parts.Length)
        {
            return "";
        }
        return FormulaPattern().IsMatch(parts[at + 1]) ? parts[at + 1] : "";
    }

    /// <summary><c>true</c> when <paramref name="resolved"/> is the <c>claude</c> file of a Claude Code Homebrew cask (stable or <c>@latest</c>).</summary>
    public static bool IsClaudeCaskBinary(string? resolved)
    {
        if (string.IsNullOrEmpty(resolved) || !resolved.StartsWith('/'))
        {
            return false;
        }
        var parts = Segments(resolved);
        var at = Array.IndexOf(parts, "Caskroom");
        return parts.Length > 0 && parts[^1] == "claude" && at >= 0 && at + 1 < parts.Length
            && ClaudeCasks.Contains(parts[at + 1], StringComparer.Ordinal);
    }

    /// <summary>Where this CLI's newest version is published, or "" when there is no query-only source.</summary>
    public static string LatestUrl(string command, string formula = "", bool isClaudeCask = false)
    {
        if (isClaudeCask)
        {
            return ClaudeReleaseLatestUrl;
        }
        if (formula.Length > 0)
        {
            return $"{HomebrewFormulaApi}/{formula}.json";
        }
        if (NpmPackages.TryGetValue(command, out var package))
        {
            return $"{NpmRegistry}/-/package/{package.Replace("/", "%2F", StringComparison.Ordinal)}/dist-tags";
        }
        return CursorCommands.Contains(command) ? CursorInstallUrl : "";
    }

    /// <summary>The name of the source <see cref="LatestUrl"/> picks: anthropic, homebrew, npm, cursor or "".</summary>
    public static string LatestSource(string command, string formula = "", bool isClaudeCask = false)
    {
        if (isClaudeCask)
        {
            return "anthropic";
        }
        if (formula.Length > 0)
        {
            return "homebrew";
        }
        if (NpmPackages.ContainsKey(command))
        {
            return "npm";
        }
        return CursorCommands.Contains(command) ? "cursor" : "";
    }

    /// <summary>The newest version in what that CLI's source answered; "" when it cannot be read.</summary>
    public static string ParseLatest(string command, byte[] body, string formula = "", bool isClaudeCask = false)
    {
        if (isClaudeCask)
        {
            var version = ParseVersion(Encoding.UTF8.GetString(body));
            return PlainVersionPattern().IsMatch(version) ? version : "";
        }
        if (formula.Length > 0)
        {
            var versions = Member(Root(body), "versions");
            return versions is { ValueKind: JsonValueKind.Object } ? ParseVersion(Text(Member(versions, "stable"))) : "";
        }
        if (NpmPackages.ContainsKey(command))
        {
            return ParseVersion(Text(Member(Root(body), "latest")));
        }
        if (CursorCommands.Contains(command))
        {
            var match = CursorBuildPattern().Match(Encoding.UTF8.GetString(body));
            return match.Success ? ParseVersion(match.Groups[1].Value) : "";
        }
        return "";
    }

    private static string[] Segments(string? path) =>
        (path ?? "").Split('/', StringSplitOptions.RemoveEmptyEntries);

    private static JsonElement? Root(byte[] body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            return document.RootElement.ValueKind == JsonValueKind.Object ? document.RootElement.Clone() : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static JsonElement? Member(JsonElement? element, string name) =>
        element is { ValueKind: JsonValueKind.Object } e && e.TryGetProperty(name, out var value) ? value : null;

    private static string Text(JsonElement? value) => value switch
    {
        { ValueKind: JsonValueKind.String } s => s.GetString() ?? "",
        { ValueKind: JsonValueKind.Number } n => n.GetRawText(),
        _ => "",
    };
}
