using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Catalog;

/// <summary>
/// The last model list each CLI gave, kept on disk so an agent offline, or whose CLI fails, still
/// shows what it offered last time instead of a list written by hand. A file next to
/// <c>models-known.json</c>: <c>{"&lt;command&gt;": {"ids": [...], "prices": {"&lt;id&gt;": [in, out]}}}</c>.
/// </summary>
internal sealed class LastReads(string path)
{
    private Dictionary<string, (List<string> Ids, Dictionary<string, double[]> Prices)>? _reads;

    /// <summary>The file kept beside <paramref name="knownPath"/> (<c>models-known.listed.json</c>).</summary>
    public static string PathFor(string knownPath)
    {
        var full = Path.GetFullPath(knownPath);
        return Path.Combine(Path.GetDirectoryName(full) ?? ".", $"{Path.GetFileNameWithoutExtension(full)}.listed.json");
    }

    /// <summary>The last list <paramref name="command"/> gave, when one was kept.</summary>
    public bool TryGet(string command, out List<string> ids, out Dictionary<string, double[]> prices)
    {
        if (Load().TryGetValue(command, out var read) && read.Ids.Count > 0)
        {
            ids = [.. read.Ids];
            prices = new Dictionary<string, double[]>(read.Prices, StringComparer.Ordinal);
            return true;
        }
        ids = [];
        prices = [];
        return false;
    }

    /// <summary>Keeps <paramref name="command"/>'s list; a write that fails leaves it in memory only.</summary>
    public void Save(string command, List<string> ids, Dictionary<string, double[]> prices)
    {
        _reads = null; // another host may have kept another CLI's list since this one read the file
        var reads = Load();
        reads[command] = ([.. ids], new Dictionary<string, double[]>(prices, StringComparer.Ordinal));
        var root = new JsonObject();
        foreach (var (key, read) in reads.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var priceNode = new JsonObject();
            foreach (var (id, price) in read.Prices.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                priceNode[id] = new JsonArray(price.Select(v => (JsonNode?)JsonValue.Create(v)).ToArray());
            }
            root[key] = new JsonObject
            {
                ["ids"] = new JsonArray(read.Ids.Select(m => (JsonNode?)JsonValue.Create(m)).ToArray()),
                ["prices"] = priceNode,
            };
        }
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)) ?? ".");
            var tmp = Path.ChangeExtension(path, ".tmp");
            File.WriteAllText(tmp, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            File.Move(tmp, path, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Kept in memory; the next successful read tries the file again.
        }
    }

    private Dictionary<string, (List<string> Ids, Dictionary<string, double[]> Prices)> Load()
    {
        if (_reads is not null)
        {
            return _reads;
        }
        _reads = new(StringComparer.Ordinal);
        try
        {
            if (JsonNode.Parse(File.ReadAllText(path)) is not JsonObject root)
            {
                return _reads;
            }
            foreach (var (command, node) in root)
            {
                if (node is JsonObject read && read["ids"] is JsonArray idNodes)
                {
                    var ids = idNodes.OfType<JsonValue>()
                        .Where(v => v.GetValueKind() == JsonValueKind.String)
                        .Select(v => v.GetValue<string>())
                        .Where(ModelListParser.IsModelId)
                        .Take(ModelListParser.MaxModels)
                        .ToList();
                    _reads[command] = (ids, ReadPrices(read["prices"] as JsonObject));
                }
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException or InvalidOperationException)
        {
            // No file yet, or one this version cannot read: nothing was kept.
        }
        return _reads;
    }

    private static Dictionary<string, double[]> ReadPrices(JsonObject? node)
    {
        var prices = new Dictionary<string, double[]>(StringComparer.Ordinal);
        foreach (var (id, value) in node ?? [])
        {
            if (value is JsonArray { Count: 2 } pair && Price(pair[0]) is double input && Price(pair[1]) is double output)
            {
                prices[id] = [input, output];
            }
        }
        return prices;
    }

    private static double? Price(JsonNode? node) =>
        node is JsonValue value && value.GetValueKind() == JsonValueKind.Number && value.TryGetValue<double>(out var d)
            && double.IsFinite(d) && d >= 0 ? d : null;
}
