using System.Text.Json;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Login;

/// <summary>Reads what a CLI's sign-in prints: the link, the device code, the status, and the output safe to show.</summary>
public static partial class LoginText
{
    /// <summary>How much of a CLI's output is ever shown.</summary>
    public const int OutputTail = 4000;

    [GeneratedRegex("https://[^\\s\"'<>]+")]
    private static partial Regex UrlRe();

    // Bearer values and API-key shapes. A key does not have to start with sk-.
    [GeneratedRegex(
        @"\b(?:sk-[a-z0-9_-]{8,}|sk-or-v1-[a-z0-9]+|xai-[a-z0-9_-]{8,})\b"
        + @"|\bbearer\s+[a-z0-9._~+/=-]{16,}"
        + @"|\b(?:api[-_\s]?key|x-api-key)\s*[:=]\s*[""']?[a-z0-9._~+/=-]{8,}"
        + @"|\b(?:ghp|gho|ghu|ghs|ghr)_[a-z0-9]{16,}\b"
        + @"|\bgithub_pat_[a-z0-9_]{22,}\b",
        RegexOptions.IgnoreCase)]
    private static partial Regex SecretRe();

    [GeneratedRegex("\u001b\\[[0-9;]*m")]
    private static partial Regex AnsiRe();

    // "code: ABCD", or with no separator (Copilot's "enter code 92EC-55BB") only a dashed code.
    [GeneratedRegex(
        @"(?:user[_ ]code|enter(?: the)? code|one-time code|shows this code)"
        + @"(?:\s*[:=]\s*([A-Z0-9]{4,8}(?:-[A-Z0-9]{4,8})?)|\s+([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\b)",
        RegexOptions.IgnoreCase)]
    private static partial Regex UserCodeRe();

    [GeneratedRegex(@"\b0 credentials\b")]
    private static partial Regex ZeroCredentials();

    // A credential line names the provider and its kind alone (`●  OpenRouter api`).
    [GeneratedRegex(@"^\W*openrouter\s+(?:api|oauth|wellknown)\s*$", RegexOptions.Multiline)]
    private static partial Regex OpenRouterCredential();

    /// <summary>The first https link on one of <paramref name="hosts"/> in the CLI's output, else "".</summary>
    public static string Link(string text, IReadOnlyList<string> hosts)
    {
        foreach (Match match in UrlRe().Matches(text))
        {
            var url = match.Value.TrimEnd('.', ',', ';', ')');
            if (Uri.TryCreate(url, UriKind.Absolute, out var uri)
                && uri.Scheme == Uri.UriSchemeHttps
                && hosts.Contains(uri.IdnHost.ToLowerInvariant(), StringComparer.Ordinal))
            {
                return url;
            }
        }
        return "";
    }

    /// <summary>The short device code a page asks the owner to type, if the CLI printed one.</summary>
    public static string UserCode(string? text)
    {
        text ??= "";
        foreach (Match match in UrlRe().Matches(text))
        {
            if (!Uri.TryCreate(match.Value.TrimEnd('.', ',', ';', ')'), UriKind.Absolute, out var uri))
            {
                continue;
            }
            foreach (var pair in uri.Query.TrimStart('?').Split('&'))
            {
                var at = pair.IndexOf('=');
                if (at > 0 && pair[..at] == "user_code" && Uri.UnescapeDataString(pair[(at + 1)..]).Trim() is { Length: > 0 } code)
                {
                    return code;
                }
            }
        }
        var found = UserCodeRe().Match(text);
        return found.Success ? (found.Groups[1].Success ? found.Groups[1].Value : found.Groups[2].Value).ToUpperInvariant() : "";
    }

    /// <summary><c>&lt;cli&gt; status</c> → true / false, or null when the answer says neither.</summary>
    public static bool? ParseSignedIn(int exitCode, string? output)
    {
        var text = AnsiRe().Replace(output ?? "", "");
        var json = FromJson(text);
        if (json is not null)
        {
            return json;
        }
        var lowered = text.ToLowerInvariant();
        if (lowered.Contains("not logged in") || lowered.Contains("not authenticated") || lowered.Contains("authentication required"))
        {
            return false;
        }
        // OpenCode's `auth list` names OpenRouter even when empty: 0 credentials wins.
        if (ZeroCredentials().IsMatch(lowered) || lowered.Contains("no credentials"))
        {
            return false;
        }
        if (OpenRouterCredential().IsMatch(lowered))
        {
            return true;
        }
        return exitCode == 0 && (lowered.Contains("logged in") || lowered.Contains("signed in")) ? true : null;
    }

    /// <summary>The last bytes of CLI output with bearer tokens and API keys stripped (never shown in the UI).</summary>
    public static string Tail(string? text)
    {
        text ??= "";
        var tail = text.Length > OutputTail ? text[^OutputTail..] : text;
        return SecretRe().Replace(tail.Trim(), "[redacted]");
    }

    private static bool? FromJson(string text)
    {
        // The first JSON-looking chunk decides: the whole text, then each line.
        foreach (var chunk in new[] { text.Trim() }.Concat(text.Split('\n').Select(line => line.Trim())))
        {
            if (!chunk.StartsWith('{'))
            {
                continue;
            }
            try
            {
                using var doc = JsonDocument.Parse(chunk);
                if (doc.RootElement.ValueKind == JsonValueKind.Object
                    && doc.RootElement.TryGetProperty("loggedIn", out var value)
                    && value.ValueKind is JsonValueKind.True or JsonValueKind.False)
                {
                    return value.GetBoolean();
                }
            }
            catch (JsonException)
            {
                continue;
            }
            break;
        }
        return null;
    }
}
