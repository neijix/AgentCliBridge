using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Catalog;

/// <summary>What a company gateway's <c>/v1/models</c> offers, in its order.</summary>
/// <param name="Ids">The chat model ids.</param>
/// <param name="Prices">Model to [input, output] USD per million tokens.</param>
/// <param name="Labels">Model to its display name, when that is not the id itself.</param>
/// <param name="Toolless">The models it says cannot call tools.</param>
public sealed record GatewayModels(
    IReadOnlyList<string> Ids,
    IReadOnlyDictionary<string, double[]> Prices,
    IReadOnlyDictionary<string, string> Labels,
    IReadOnlyList<string> Toolless)
{
    private const int LabelMax = 100;
    private static readonly HashSet<string> NonChatTypes = new(StringComparer.Ordinal) { "embedding", "embeddings", "rerank", "moderation" };

    /// <summary>Where a gateway lists its models: the URL Claude Code's own model discovery reads.</summary>
    public static string UrlFor(string baseUrl) => $"{baseUrl.Trim().TrimEnd('/')}/v1/models?limit=1000";

    /// <summary>
    /// The models of a <c>/v1/models</c> answer (Anthropic's shape, or OpenAI's and LiteLLM's
    /// <c>data</c>). An entry counts when its <c>id</c> looks like a model id and it writes text.
    /// <c>display_name</c> is its label, <c>info.*_cost_per_token</c> its price (none when both are
    /// zero), and <c>capabilities.tools: false</c> makes it toolless.
    /// </summary>
    public static GatewayModels Parse(JsonNode? data)
    {
        var ids = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var prices = new Dictionary<string, double[]>(StringComparer.Ordinal);
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        var toolless = new List<string>();
        var entries = (data as JsonObject)?["data"] as JsonArray;
        foreach (var node in entries ?? [])
        {
            if (ids.Count >= ModelListParser.MaxModels)
            {
                break;
            }
            if (!TryAcceptEntry(node, seen, out var entry, out var model))
            {
                continue;
            }
            seen.Add(model);
            ids.Add(model);
            var label = Label(Str(entry["display_name"]), model);
            if (label.Length > 0)
            {
                labels[model] = label;
            }
            if (TryReadPrice(entry["info"]) is { } price)
            {
                prices[model] = price;
            }
            if (entry["capabilities"] is JsonObject caps && caps["tools"] is JsonNode tools && tools.GetValueKind() == JsonValueKind.False)
            {
                toolless.Add(model);
            }
        }
        return new GatewayModels(ids, prices, labels, toolless);
    }

    private static bool TryAcceptEntry(JsonNode? node, HashSet<string> seen, out JsonObject entry, out string model)
    {
        entry = null!;
        model = "";
        if (node is not JsonObject obj || Str(obj["id"]) is not { Length: <= 200 } id
            || !ModelListParser.IsModelId(id) || seen.Contains(id))
        {
            return false;
        }
        if (NonChatTypes.Contains((Str(obj["type"]) ?? "").ToLowerInvariant()))
        {
            return false;
        }
        if (obj["output_modalities"] is JsonArray outputs && outputs.Count > 0
            && !outputs.Any(o => Str(o) == "text"))
        {
            return false;
        }
        entry = obj;
        model = id;
        return true;
    }

    private static double[]? TryReadPrice(JsonNode? infoNode)
    {
        if (infoNode is JsonObject info
            && PerMillion(info["input_cost_per_token"]) is double costIn
            && PerMillion(info["output_cost_per_token"]) is double costOut
            && (costIn != 0 || costOut != 0))
        {
            return [costIn, costOut];
        }
        return null;
    }

    private static string? Str(JsonNode? node) =>
        node is JsonValue v && v.GetValueKind() == JsonValueKind.String ? v.GetValue<string>() : null;

    private static double? PerMillion(JsonNode? node)
    {
        if (node is JsonValue v && v.GetValueKind() == JsonValueKind.Number && v.TryGetValue<double>(out var d)
            && double.IsFinite(d) && d >= 0)
        {
            return Math.Round(d * 1_000_000, 4);
        }
        return null;
    }

    private static string Label(string? name, string model)
    {
        if (name is null)
        {
            return "";
        }
        var clean = string.Concat(name.Select(ch => char.IsControl(ch) ? ' ' : ch));
        var label = string.Join(' ', clean.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        label = label[..Math.Min(label.Length, LabelMax)];
        return label == model ? "" : label;
    }
}
