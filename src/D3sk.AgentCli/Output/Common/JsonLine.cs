using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Common;

/// <summary>
/// One non-empty stdout line, and the JSON value it held when it parsed.
/// <paramref name="Parsed"/> is false when the line is not JSON. JSON <c>null</c> does parse:
/// <paramref name="Parsed"/> is true and <paramref name="Value"/> is null, so a caller must not
/// treat null as "not JSON". Antigravity shows a non-object line as text; the other parsers skip a
/// line that did not parse.
/// </summary>
/// <param name="Text">The line as UTF-8 text, trimmed.</param>
/// <param name="Value">The parsed JSON value; null when it did not parse, or the line was <c>null</c>.</param>
/// <param name="Parsed">Whether the line was valid JSON.</param>
public sealed record JsonLine(string Text, JsonNode? Value, bool Parsed)
{
    /// <summary>Decodes each non-empty line of <paramref name="lines"/> and parses it as one JSON value; a line that is not JSON comes back unparsed instead of throwing.</summary>
    public static async IAsyncEnumerable<JsonLine> ReadAsync(IAsyncEnumerable<ChildLine> lines)
    {
        await foreach (var line in lines)
        {
            var text = line.Text.Trim();
            if (text.Length == 0)
            {
                continue;
            }

            yield return Parse(text);
        }
    }

    /// <summary>Parses one trimmed, non-empty line.</summary>
    public static JsonLine Parse(string text)
    {
        try
        {
            return new JsonLine(text, JsonNode.Parse(text), true);
        }
        catch (Exception e) when (e is JsonException or ArgumentException)
        {
            return new JsonLine(text, null, false);
        }
    }

    /// <summary>The line's value as an object, or an empty one: a CLI line may carry any JSON value.</summary>
    public JsonObject AsObject() => Json.AsObject(Value);
}
