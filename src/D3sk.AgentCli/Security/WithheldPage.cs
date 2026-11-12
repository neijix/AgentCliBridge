using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Security;

/// <summary>What a scout <c>fetch</c> result says about a page it withheld.</summary>
/// <param name="Url">The page, "" when the result does not name it.</param>
/// <param name="Passages">The flagged passages, each clipped.</param>
/// <param name="Risk">The injection risk level the scout gave.</param>
public sealed record WithheldPage(string Url, IReadOnlyList<string> Passages, string Risk)
{
    private static readonly string[] PassageKeys = ["flagged_passages", "flagged", "passages", "findings", "reasons"];

    /// <summary>
    /// Reads the scout's JSON envelope (<c>withheld</c> / <c>injection_risk</c>), with a text fallback for a
    /// result that is not plain JSON; null when the page came back.
    /// </summary>
    public static WithheldPage? Parse(string? output)
    {
        JsonNode? data = null;
        try
        {
            data = JsonNode.Parse(output ?? "");
        }
        catch (JsonException)
        {
        }
        if (data is JsonObject obj)
        {
            return FromEnvelope(obj);
        }
        var lowered = (output ?? "").ToLowerInvariant();
        return lowered.Contains("\"withheld\": true", StringComparison.Ordinal) || lowered.Contains("\"injection_risk\": \"high\"", StringComparison.Ordinal)
            ? new WithheldPage("", [SecurityText.Clip(output!, 300)], "high")
            : null;
    }

    private static WithheldPage? FromEnvelope(JsonObject data)
    {
        var risk = data["injection_risk"];
        if (risk is JsonObject level)
        {
            risk = level["level"];
        }
        var riskText = risk switch
        {
            null => "None",
            JsonValue v when v.TryGetValue<string>(out var s) => s,
            _ => risk.ToJsonString(),
        };
        var withheld = data["withheld"] is JsonValue w && w.TryGetValue<bool>(out var b) && b;
        if (!withheld && !riskText.Equals("high", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }
        return new WithheldPage(
            SecurityText.FirstString(data, SecurityText.UrlKeys), ReadPassages(data), string.IsNullOrEmpty(riskText) || riskText == "None" ? "high" : riskText);
    }

    private static List<string> ReadPassages(JsonObject data)
    {
        foreach (var key in PassageKeys)
        {
            if (data[key] is JsonArray list)
            {
                return list.Take(5).Select(p => SecurityText.Clip(p, 300)).ToList();
            }
            if (data[key] is JsonValue v && v.TryGetValue<string>(out var s) && !string.IsNullOrWhiteSpace(s))
            {
                return [SecurityText.Clip(s, 300)];
            }
        }
        return [];
    }
}
