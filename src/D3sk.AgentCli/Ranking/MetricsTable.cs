using System.Text.Json;

namespace D3sk.AgentCli.Ranking;

/// <summary>One model variant's Artificial Analysis figures: the Intelligence Index and the median output speed (tokens/s, null when unknown).</summary>
public readonly record struct MetricPair(int Intelligence, int? Speed);

/// <summary>Family, then effort, then its figures. Effort is one of max, xhigh, high, medium, low.</summary>
public sealed class MetricsTable : Dictionary<string, Dictionary<string, MetricPair>>
{
    /// <summary>Validates a table read from disk or the network: unknown shapes and non-positive figures are dropped, never thrown on.</summary>
    public static MetricsTable Sanitize(JsonElement raw)
    {
        var cleaned = new MetricsTable();
        if (raw.ValueKind != JsonValueKind.Object)
        {
            return cleaned;
        }

        foreach (var family in raw.EnumerateObject())
        {
            if (family.Name.Length == 0 || family.Value.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var variants = new Dictionary<string, MetricPair>();
            foreach (var effort in family.Value.EnumerateObject())
            {
                if (effort.Name.Length > 0 && ValidPair(effort.Value) is { } pair)
                {
                    variants[effort.Name] = pair;
                }
            }

            if (variants.Count > 0)
            {
                cleaned[family.Name] = variants;
            }
        }

        return cleaned;
    }

    /// <summary>Same, from the JSON text of <c>models-metrics.json</c>; text that does not parse gives an empty table.</summary>
    public static MetricsTable Sanitize(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return Sanitize(doc.RootElement);
        }
        catch (JsonException)
        {
            return new MetricsTable();
        }
    }

    internal static bool IsPositiveNumber(JsonElement value, out double number)
    {
        number = 0;
        return value.ValueKind == JsonValueKind.Number
            && value.TryGetDouble(out number)
            && double.IsFinite(number)
            && number > 0;
    }

    private static MetricPair? ValidPair(JsonElement pair)
    {
        if (pair.ValueKind != JsonValueKind.Array || pair.GetArrayLength() == 0
            || !IsPositiveNumber(pair[0], out var intelligence))
        {
            return null;
        }

        int? speed = pair.GetArrayLength() > 1 && IsPositiveNumber(pair[1], out var s) ? (int)Math.Round(s) : null;
        return new MetricPair((int)Math.Round(intelligence), speed);
    }
}
