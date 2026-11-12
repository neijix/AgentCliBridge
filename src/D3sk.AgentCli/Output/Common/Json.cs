using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Output.Common;

/// <summary>Reading helpers every stdout parser shares.</summary>
public static class Json
{
    /// <summary><paramref name="value"/> when it is a JSON object, else an empty one.</summary>
    public static JsonObject AsObject(JsonNode? value) => value as JsonObject ?? [];

    /// <summary>
    /// The CLI's whole tool result as text when the parser kept less of it; "" when it kept it all.
    /// InjectionGuard scans this too (<c>ToolResult.Raw</c>): a field the parser does not show is
    /// still text the model read. A non-string value is its Python <c>json.dumps(ensure_ascii=False)</c>
    /// text (<c>", "</c> and <c>": "</c> separators) so the frozen stream captures match.
    /// </summary>
    public static string RawText(JsonNode? value, string kept)
    {
        if (value is null)
        {
            return "";
        }

        var raw = AsString(value) ?? Dumps(value);
        return raw == kept ? "" : raw;
    }

    /// <summary>Formats <paramref name="node"/> as Python's <c>json.dumps(value, ensure_ascii=False)</c> does.</summary>
    public static string Dumps(JsonNode? node)
    {
        var text = new StringBuilder();
        WriteNode(text, node);
        return text.ToString();
    }

    private static void WriteNode(StringBuilder text, JsonNode? node)
    {
        switch (node)
        {
            case JsonObject obj:
                text.Append('{');
                var first = true;
                foreach (var (key, value) in obj)
                {
                    text.Append(first ? "" : ", ");
                    first = false;
                    WriteString(text, key);
                    text.Append(": ");
                    WriteNode(text, value);
                }

                text.Append('}');
                break;
            case JsonArray array:
                text.Append('[');
                for (var i = 0; i < array.Count; i++)
                {
                    text.Append(i == 0 ? "" : ", ");
                    WriteNode(text, array[i]);
                }

                text.Append(']');
                break;
            case JsonValue v when AsString(v) is { } s:
                WriteString(text, s);
                break;
            case null:
                text.Append("null");
                break;
            default:
                text.Append(node.ToJsonString());
                break;
        }
    }

    private static void WriteString(StringBuilder text, string value)
    {
        text.Append('"');
        foreach (var c in value)
        {
            switch (c)
            {
                case '"': text.Append("\\\""); break;
                case '\\': text.Append("\\\\"); break;
                case '\n': text.Append("\\n"); break;
                case '\r': text.Append("\\r"); break;
                case '\t': text.Append("\\t"); break;
                case '\b': text.Append("\\b"); break;
                case '\f': text.Append("\\f"); break;
                case < ' ': text.Append($"\\u{(int)c:x4}"); break;
                default: text.Append(c); break;
            }
        }

        text.Append('"');
    }

    /// <summary>The string value of <paramref name="value"/>, or null when it is not a JSON string.</summary>
    public static string? AsString(JsonNode? value) =>
        value is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    /// <summary>Python truthiness of a JSON value: null, false, 0, "", [] and {} are not.</summary>
    public static bool IsTruthy(JsonNode? value) => value switch
    {
        null => false,
        JsonArray a => a.Count > 0,
        JsonObject o => o.Count > 0,
        JsonValue v => v.GetValueKind() switch
        {
            JsonValueKind.False or JsonValueKind.Null => false,
            JsonValueKind.String => v.GetValue<string>().Length > 0,
            JsonValueKind.Number => v.GetValue<JsonElement>().GetDouble() != 0,
            _ => true,
        },
        _ => true,
    };
}
