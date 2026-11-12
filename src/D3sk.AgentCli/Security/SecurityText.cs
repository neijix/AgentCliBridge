using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Security;

/// <summary>Text handling for the security log: token redaction, clipping, and reading arguments.</summary>
internal static partial class SecurityText
{
    /// <summary>Longest text a log field keeps.</summary>
    internal const int MaxText = 600;

    /// <summary>Argument and result fields that name a page or resource.</summary>
    internal static readonly string[] UrlKeys = ["url", "uri", "href", "link", "page_url", "source_url"];

    private static readonly string[] TokenEnvKeys = ["BRIDGE_TOKEN", "BRIDGE_OWNER_TOKEN"];

    /// <summary>JSON as the log writes it: one line, non-ASCII kept.</summary>
    internal static readonly JsonSerializerOptions Json = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    /// <summary>Drops token values: this process's bridge tokens, bearer tokens, and token assignments.</summary>
    internal static string Redact(string text)
    {
        foreach (var key in TokenEnvKeys)
        {
            var value = Environment.GetEnvironmentVariable(key)?.Trim() ?? "";
            if (value.Length >= 8 && text.Contains(value, StringComparison.Ordinal))
            {
                text = text.Replace(value, "[redacted]", StringComparison.Ordinal);
            }
        }
        text = Bearer().Replace(text, "$1[redacted]");
        return TokenAssign().Replace(text, "$1[redacted]");
    }

    /// <summary>A copy of the JSON value with every string (and object key) redacted.</summary>
    internal static JsonNode? RedactNode(JsonNode? node) => node switch
    {
        JsonObject o => new JsonObject(o.Select(p => KeyValuePair.Create(Redact(p.Key), RedactNode(p.Value)))),
        JsonArray a => new JsonArray(a.Select(RedactNode).ToArray()),
        JsonValue v when v.TryGetValue<string>(out var s) => JsonValue.Create(Redact(s)),
        null => null,
        _ => node.DeepClone(),
    };

    /// <summary>Redacted text, cut to <paramref name="limit"/> characters with an ellipsis.</summary>
    internal static string Clip(string text, int limit = MaxText)
    {
        text = Redact(text);
        return text.Length <= limit ? text : string.Concat(text.AsSpan(0, limit - 1), "…");
    }

    /// <summary>Clip for a JSON value: a string as is, anything else as compact JSON.</summary>
    internal static string Clip(JsonNode? node, int limit = MaxText) =>
        Clip(node is JsonValue v && v.TryGetValue<string>(out var s) ? s : node?.ToJsonString(Json) ?? "null", limit);

    /// <summary>The first non-blank string among <paramref name="keys"/> of a JSON object, trimmed; "" when none.</summary>
    internal static string FirstString(JsonNode? mapping, params string[] keys)
    {
        if (mapping is not JsonObject obj)
        {
            return "";
        }
        foreach (var key in keys)
        {
            if (obj[key] is JsonValue v && v.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
            {
                return s.Trim();
            }
        }
        return "";
    }

    [GeneratedRegex(@"(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", RegexOptions.IgnoreCase)]
    private static partial Regex Bearer();

    [GeneratedRegex(
        @"((?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|token)\s*[=:]\s*)[^\s&""']{8,}",
        RegexOptions.IgnoreCase)]
    private static partial Regex TokenAssign();
}
