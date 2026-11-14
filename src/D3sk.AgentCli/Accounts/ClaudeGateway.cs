using System.Collections;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Accounts;

/// <summary>
/// An ordered name to value map of HTTP headers. Names compare case-insensitively and insertion
/// order is kept; setting a name already present, in any case, replaces its value at the first
/// position and takes the later name's spelling.
/// </summary>
public sealed class GatewayHeaders : IReadOnlyDictionary<string, string>
{
    private readonly List<KeyValuePair<string, string>> _items = [];

    /// <summary>The empty set: a home with no gateway.</summary>
    public static GatewayHeaders Empty => new();

    internal void Set(string name, string value)
    {
        var at = _items.FindIndex(i => string.Equals(i.Key, name, StringComparison.OrdinalIgnoreCase));
        if (at < 0)
        {
            _items.Add(new(name, value));
        }
        else
        {
            _items[at] = new(name, value);
        }
    }

    /// <inheritdoc />
    public int Count => _items.Count;

    /// <inheritdoc />
    public IEnumerable<string> Keys => _items.Select(i => i.Key);

    /// <inheritdoc />
    public IEnumerable<string> Values => _items.Select(i => i.Value);

    /// <inheritdoc />
    public string this[string key] =>
        TryGetValue(key, out var value) ? value : throw new KeyNotFoundException(key);

    /// <inheritdoc />
    public bool ContainsKey(string key) => TryGetValue(key, out _);

    /// <inheritdoc />
    public bool TryGetValue(string key, out string value)
    {
        foreach (var item in _items)
        {
            if (string.Equals(item.Key, key, StringComparison.OrdinalIgnoreCase))
            {
                value = item.Value;
                return true;
            }
        }
        value = "";
        return false;
    }

    /// <inheritdoc />
    public IEnumerator<KeyValuePair<string, string>> GetEnumerator() => _items.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}

/// <summary>
/// The company gateway a Claude home talks to and the headers Claude Code sends it, read from
/// files and the given environment only (an <c>apiKeyHelper</c> script is never run). The
/// environment Claude Code runs with is the given one with the <c>env</c> object of
/// <c>settings.json</c> (in <c>CLAUDE_CONFIG_DIR</c> when set, else <c>&lt;home&gt;/.claude</c>) on top.
/// </summary>
public static partial class ClaudeGateway
{
    private static readonly string[] CloudSwitches = ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"];

    // Python str.splitlines' separators; a CR LF pair is one.
    private static readonly char[] LineSeparators = ['\n', '\r', '\v', '\f', '\u001c', '\u001d', '\u001e', '\u0085', '\u2028', '\u2029'];

    [GeneratedRegex("^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$")]
    private static partial Regex HeaderName();

    /// <summary>
    /// <c>ANTHROPIC_BASE_URL</c> (trimmed) of a Claude home, or <c>null</c> for Anthropic's own API,
    /// a URL that is not http(s) or has a bad port, and Bedrock / Vertex / Foundry.
    /// </summary>
    public static string? Url(string home, IReadOnlyDictionary<string, string> env)
    {
        var merged = MergedEnv(home, env);
        var baseUrl = (merged.GetValueOrDefault("ANTHROPIC_BASE_URL") ?? "").Trim();
        return CloudSwitch(merged) is null && IsGatewayUrl(baseUrl) ? baseUrl : null;
    }

    /// <summary>
    /// The headers Claude Code sends that gateway: <c>ANTHROPIC_CUSTOM_HEADERS</c> lines, then
    /// <c>x-api-key</c> and <c>Authorization: Bearer</c>; empty when the home has no gateway.
    /// </summary>
    public static GatewayHeaders Headers(string home, IReadOnlyDictionary<string, string> env)
    {
        var headers = new GatewayHeaders();
        if (Url(home, env) is null)
        {
            return headers;
        }
        var merged = MergedEnv(home, env);
        foreach (var line in SplitLines(merged.GetValueOrDefault("ANTHROPIC_CUSTOM_HEADERS") ?? ""))
        {
            var colon = line.IndexOf(':');
            if (colon < 0)
            {
                continue;
            }
            var name = line[..colon].Trim();
            var value = line[(colon + 1)..].Trim();
            if (HeaderName().IsMatch(name) && value.Length > 0 && IsPrintable(value))
            {
                headers.Set(name, value);
            }
        }
        var apiKey = (merged.GetValueOrDefault("ANTHROPIC_API_KEY") ?? "").Trim();
        var token = (merged.GetValueOrDefault("ANTHROPIC_AUTH_TOKEN") ?? "").Trim();
        if (apiKey.Length > 0 && IsPrintable(apiKey))
        {
            headers.Set("x-api-key", apiKey);
        }
        if (token.Length > 0 && IsPrintable(token))
        {
            headers.Set("Authorization", "Bearer " + token);
        }
        return headers;
    }

    /// <summary>The environment Claude Code runs with: the given one, its settings' <c>env</c> on top.</summary>
    internal static Dictionary<string, string> MergedEnv(string home, IReadOnlyDictionary<string, string> env)
    {
        var merged = new Dictionary<string, string>(env, StringComparer.Ordinal);
        var configured = (env.GetValueOrDefault("CLAUDE_CONFIG_DIR") ?? "").Trim();
        var dir = configured.Length > 0 ? configured : Path.Combine(home, ".claude");
        if (ReadJson(Path.Combine(dir, "settings.json")) is JsonObject root && root["env"] is JsonObject found)
        {
            foreach (var (key, value) in found)
            {
                if (value is JsonValue v && v.TryGetValue<string>(out var text))
                {
                    merged[key] = text;
                }
            }
        }
        return merged;
    }

    /// <summary>The first cloud switch that is on (Bedrock, Vertex, Foundry), or <c>null</c>.</summary>
    internal static string? CloudSwitch(IReadOnlyDictionary<string, string> merged) =>
        CloudSwitches.FirstOrDefault(s => IsOn(merged.GetValueOrDefault(s) ?? ""));

    internal static bool IsOn(string value) =>
        value.Trim().ToLowerInvariant() is not ("" or "0" or "false" or "no" or "off");

    internal static JsonNode? ReadJson(string path)
    {
        try
        {
            return JsonNode.Parse(File.ReadAllText(path, Encoding.UTF8));
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }

    private static bool IsGatewayUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https"))
        {
            return false;
        }
        var host = uri.Host.ToLowerInvariant();
        return host.Length > 0 && host != "anthropic.com" && !host.EndsWith(".anthropic.com", StringComparison.Ordinal);
    }

    private static IEnumerable<string> SplitLines(string text)
    {
        var start = 0;
        for (var i = 0; i < text.Length; i++)
        {
            if (Array.IndexOf(LineSeparators, text[i]) < 0)
            {
                continue;
            }
            yield return text[start..i];
            if (text[i] == '\r' && i + 1 < text.Length && text[i + 1] == '\n')
            {
                i++;
            }
            start = i + 1;
        }
        if (start < text.Length)
        {
            yield return text[start..];
        }
    }

    /// <summary>Python <c>str.isprintable</c>: no Cc, Cf, Cs, Co, Cn, Zl, Zp or Zs other than U+0020.</summary>
    private static bool IsPrintable(string text)
    {
        for (var i = 0; i < text.Length; i++)
        {
            Rune rune;
            if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
            {
                rune = new Rune(text[i], text[i + 1]);
                i++;
            }
            else if (char.IsSurrogate(text[i]))
            {
                return false;
            }
            else
            {
                rune = new Rune(text[i]);
            }
            if (rune.Value == ' ')
            {
                continue;
            }
            if (Rune.GetUnicodeCategory(rune) is UnicodeCategory.Control or UnicodeCategory.Format
                or UnicodeCategory.Surrogate or UnicodeCategory.PrivateUse or UnicodeCategory.OtherNotAssigned
                or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator or UnicodeCategory.SpaceSeparator)
            {
                return false;
            }
        }
        return true;
    }
}
