using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Output.Common;

namespace D3sk.AgentCli.Local;

/// <summary>Reads the OpenAI-compatible stream D3SKMODEL answers a chat with.</summary>
internal static class MlxSse
{
    private const string Failed = "The local model failed.";

    /// <summary>Text and thinking from one SSE line; null for a blank, a comment, <c>[DONE]</c> or junk. Throws on an error object with no choices.</summary>
    public static (string Text, string Thinking)? DeltaPair(string line)
    {
        var text = line.Trim();
        if (!text.StartsWith("data:", StringComparison.Ordinal))
        {
            return null;
        }

        var payload = text[5..].Trim();
        if (payload.Length == 0 || payload == "[DONE]")
        {
            return null;
        }

        if (Parse(payload) is not JsonObject data)
        {
            return null;
        }

        var choices = data["choices"] as JsonArray;
        if (Json.IsTruthy(data["error"]) && (choices is null || choices.Count == 0))
        {
            throw new MlxException(ErrorMessage(data["error"]));
        }

        var spoken = "";
        var thought = "";
        foreach (var choice in choices ?? [])
        {
            if (choice is not JsonObject c)
            {
                continue;
            }

            var delta = Json.AsObject(c["delta"]);
            var message = Json.AsObject(c["message"]);
            spoken += Text(delta["content"]) is { Length: > 0 } d ? d : Text(message["content"]);
            thought += Text(delta["reasoning_content"]) is { Length: > 0 } r ? r : Text(delta["reasoning"]);
        }

        return spoken.Length == 0 && thought.Length == 0 ? null : (spoken, thought);
    }

    /// <summary>The reply text of a non-streamed completion; "" when it has none. Throws on an error object.</summary>
    public static string UnaryText(string raw, string label)
    {
        if (Parse(raw) is not JsonNode node)
        {
            throw new MlxException($"{label} answered with something that is not JSON.");
        }

        if (node is not JsonObject data)
        {
            return "";
        }

        if (Json.IsTruthy(data["error"]))
        {
            throw new MlxException(ErrorMessage(data["error"]));
        }

        return data["choices"] is JsonArray { Count: > 0 } choices && choices[0] is JsonObject first
            ? Text(Json.AsObject(first["message"])["content"])
            : "";
    }

    /// <summary>The owner-facing detail of an HTTP error body: <c>detail</c>, else the OpenAI <c>error.message</c>; null when it has neither.</summary>
    public static string? ErrorDetail(string body)
    {
        if (Parse(body) is not JsonObject data)
        {
            return null;
        }

        var detail = Text(data["detail"]);
        if (detail.Length == 0 && data["error"] is JsonObject error)
        {
            detail = Text(error["message"]);
        }

        return detail.Length == 0 ? null : detail;
    }

    private static string ErrorMessage(JsonNode? error)
    {
        var message = error is JsonObject o ? Text(o["message"]) : Text(error);
        return message.Length == 0 ? Failed : message;
    }

    private static string Text(JsonNode? value) => Json.AsString(value) ?? "";

    private static JsonNode? Parse(string text)
    {
        try
        {
            return JsonNode.Parse(text);
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
