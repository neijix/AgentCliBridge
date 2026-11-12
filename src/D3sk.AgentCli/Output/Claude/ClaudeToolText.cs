using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using D3sk.AgentCli.Output.Common;

namespace D3sk.AgentCli.Output.Claude;

/// <summary>The text of a stream-json <c>tool_result</c> content, Grok's wrapped results included.</summary>
public static partial class ClaudeToolText
{
    [GeneratedRegex("\u001b\\[[0-9;?]*[A-Za-z]")]
    private static partial Regex AnsiEscape();

    /// <summary>Flattens a tool_result content: a string, or a list of text blocks; any other value is its JSON.</summary>
    public static string Flatten(JsonNode? content)
    {
        if (content is JsonArray parts)
        {
            return string.Join("\n", parts
                .OfType<JsonObject>()
                .Where(part => Json.AsString(part["type"]) == "text")
                .Select(part => Json.AsString(part["text"]) ?? ""));
        }

        if (Json.AsString(content) is { } text)
        {
            return UnwrapGrok(text);
        }

        return content is null ? "" : Json.Dumps(content);
    }

    /// <summary>
    /// The whole tool result as text when <see cref="Flatten"/> kept less of it; "" when it kept it all.
    /// </summary>
    public static string Raw(JsonNode? content, string kept) => Json.RawText(content, kept);

    /// <summary>
    /// Grok reports tool results as JSON: <c>{"type":"Bash","output":[byte values]}</c> (with terminal
    /// colours) or <c>{"type":"ReadFile","FileContent":{"content":…}}</c>. Any other text is returned as is.
    /// </summary>
    public static string UnwrapGrok(string text)
    {
        if (!text.StartsWith('{') || JsonLine.Parse(text).Value is not JsonObject payload)
        {
            return text;
        }

        var output = payload["output"];
        if (output is JsonArray bytes && bytes.All(IsByte))
        {
            var decoded = Encoding.UTF8.GetString(bytes.Select(b => (byte)b!.GetValue<int>()).ToArray());
            return AnsiEscape().Replace(decoded, "");
        }

        if (Json.AsString(output) is { } outputText)
        {
            return outputText;
        }

        foreach (var (_, value) in payload)
        {
            if (value is JsonObject inner && Json.AsString(inner["content"]) is { } content)
            {
                return content;
            }
        }

        return text;
    }

    private static bool IsByte(JsonNode? node) =>
        node is JsonValue v && v.GetValueKind() == JsonValueKind.Number && v.TryGetValue<int>(out var n) && n is >= 0 and < 256;
}
