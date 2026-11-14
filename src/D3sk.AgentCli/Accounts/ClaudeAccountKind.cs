using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Accounts;

/// <summary>Which account a Claude home runs on: a company's (work) or a person's (personal).</summary>
/// <param name="Kind"><c>personal</c> or <c>work</c>, the value <c>CatalogAgent.AccountKind</c> accepts.</param>
/// <param name="Detail">The gateway <c>host[:port]</c>, the cloud, or the plan.</param>
public sealed record ClaudeAccount(string Kind, string Detail);

/// <summary>
/// Reads the account kind of a Claude home from files and the given environment only (no CLI is
/// run), with the same environment merge, cloud switches and not-Anthropic-host rule as
/// <see cref="ClaudeGateway"/>.
/// </summary>
public static partial class ClaudeAccountKind
{
    private static readonly Dictionary<string, string> Clouds = new()
    {
        ["CLAUDE_CODE_USE_BEDROCK"] = "Bedrock",
        ["CLAUDE_CODE_USE_VERTEX"] = "Vertex",
        ["CLAUDE_CODE_USE_FOUNDRY"] = "Foundry",
    };

    private static readonly Dictionary<string, string> Plans = new()
    {
        ["claude_max"] = "Max",
        ["claude_pro"] = "Pro",
        ["claude_free"] = "Free",
    };

    [GeneratedRegex("^[A-Za-z][A-Za-z0-9+.-]*:")]
    private static partial Regex Scheme();

    /// <summary>
    /// The account the home runs on, or <c>null</c> when nothing says. A Bedrock / Vertex / Foundry
    /// switch on (first in that order) is <c>work</c> with the cloud's name; else an
    /// <c>ANTHROPIC_BASE_URL</c> (any scheme) on a host that is not Anthropic's is <c>work</c> with
    /// <c>host</c>, or <c>host:port</c> when the URL names a port; else the <c>oauthAccount</c> of
    /// <c>.claude.json</c> (in <c>CLAUDE_CONFIG_DIR</c> when set, else <paramref name="home"/>):
    /// a Team or Enterprise organization is <c>work</c> (<c>Team</c> / <c>Enterprise</c>), any
    /// other is <c>personal</c> (<c>Max</c> / <c>Pro</c> / <c>Free</c> / <c>claude.ai</c>).
    /// </summary>
    public static ClaudeAccount? Of(string home, IReadOnlyDictionary<string, string> env)
    {
        var merged = ClaudeGateway.MergedEnv(home, env);
        if (ClaudeGateway.CloudSwitch(merged) is { } cloud)
        {
            return new("work", Clouds[cloud]);
        }
        if (GatewayHost(merged.GetValueOrDefault("ANTHROPIC_BASE_URL") ?? "") is { } host)
        {
            return new("work", host);
        }
        var dir = ClaudeGateway.ConfigDir(home, env) ?? home;
        if (ClaudeGateway.ReadJson(Path.Combine(dir, ".claude.json")) is not JsonObject root
            || root["oauthAccount"] is not JsonObject account
            || Text(account["accountUuid"]).Length == 0)
        {
            return null;
        }
        var organization = Text(account["organizationType"]);
        return organization switch
        {
            "claude_team" or "claude_enterprise" => new("work", char.ToUpperInvariant(organization[7]) + organization[8..]),
            _ => new("personal", Plans.GetValueOrDefault(organization, "claude.ai")),
        };
    }

    private static string Text(JsonNode? node) =>
        node is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";

    /// <summary>
    /// <c>host</c> or <c>host:port</c> of a base URL whose host is set and not Anthropic's, read as
    /// Python <c>urlsplit</c> does (any scheme, a port only when written, a bad port is none).
    /// </summary>
    private static string? GatewayHost(string baseUrl)
    {
        var rest = baseUrl.Trim();
        if (Scheme().Match(rest) is { Success: true } scheme)
        {
            rest = rest[scheme.Length..];
        }
        if (!rest.StartsWith("//", StringComparison.Ordinal))
        {
            return null;
        }
        rest = rest[2..];
        var end = rest.IndexOfAny(['/', '?', '#']);
        var authority = end < 0 ? rest : rest[..end];
        authority = authority[(authority.LastIndexOf('@') + 1)..];
        string host;
        var portText = "";
        if (authority.StartsWith('['))
        {
            var close = authority.IndexOf(']');
            if (close < 0)
            {
                return null;
            }
            host = authority[1..close];
            var tail = authority[(close + 1)..];
            if (tail.Length > 0)
            {
                if (tail[0] != ':')
                {
                    return null;
                }
                portText = tail[1..];
            }
        }
        else
        {
            var colon = authority.LastIndexOf(':');
            host = colon < 0 ? authority : authority[..colon];
            portText = colon < 0 ? "" : authority[(colon + 1)..];
        }
        var port = 0;
        if (portText.Length > 0 && (!portText.All(char.IsAsciiDigit) || !int.TryParse(portText, out port) || port > 65535))
        {
            return null;
        }
        host = host.ToLowerInvariant();
        if (host.Length == 0 || host == "anthropic.com" || host.EndsWith(".anthropic.com", StringComparison.Ordinal))
        {
            return null;
        }
        return port > 0 ? $"{host}:{port}" : host;
    }
}
