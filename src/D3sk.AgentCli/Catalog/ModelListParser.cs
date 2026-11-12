using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Catalog;

/// <summary>Reads the output of <c>&lt;cli&gt; models</c>, and decides what of it is offered. Pure functions.</summary>
public static partial class ModelListParser
{
    /// <summary>The most models read from one catalog (OpenCode lists ~400).</summary>
    public const int MaxModels = 800;

    /// <summary>Ids that are not models but a "let the CLI pick" setting: never dropped.</summary>
    public static readonly IReadOnlySet<string> KeepAlways = new HashSet<string>(StringComparer.Ordinal) { "auto", "default" };

    [GeneratedRegex(@"\x1b\[[0-9;?]*[A-Za-z]")]
    private static partial Regex AnsiRx();

    [GeneratedRegex(@"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]=+-]*\z")]
    private static partial Regex IdRx();

    private static readonly char[] Bullets = ['*', '-', '•', '→', '>', ' ', '\t'];

    /// <summary>Whether <paramref name="text"/> looks like a model id (and never like a flag).</summary>
    public static bool IsModelId(string text) => IdRx().IsMatch(text);

    private static string[] Lines(string? text) =>
        AnsiRx().Replace(text ?? "", "").Split('\n');

    /// <summary>
    /// Model ids in a <c>&lt;cli&gt; models</c> output, in the CLI's order, without duplicates. Each
    /// line's first word counts when it looks like an id with a digit or a slash in it (so
    /// "Fetching", "Available", "Error:" never do). Bullets and colour codes are stripped.
    /// </summary>
    public static List<string> ParseModels(string? text)
    {
        var seen = new List<string>();
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in Lines(text))
        {
            var line = raw.Trim().TrimStart(Bullets);
            if (line.Length == 0)
            {
                continue;
            }
            var word = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[0].TrimEnd(',');
            if (word.EndsWith(':') || word.EndsWith('.') || !IdRx().IsMatch(word))
            {
                continue;
            }
            if (!word.Any(char.IsDigit) && !word.Contains('/'))
            {
                continue;
            }
            if (set.Add(word))
            {
                seen.Add(word);
            }
        }
        return seen.Take(MaxModels).ToList();
    }

    /// <summary>
    /// Ids and prices in <c>opencode models --verbose</c>: each id line is followed by its JSON. A
    /// price is [input, output] in USD per million tokens. Models that cannot write text are left
    /// out; a block that is not JSON keeps its id without a price.
    /// </summary>
    public static (List<string> Ids, Dictionary<string, double[]> Prices) ParseVerboseModels(string? text)
    {
        var ids = new List<string>();
        var set = new HashSet<string>(StringComparer.Ordinal);
        var prices = new Dictionary<string, double[]>(StringComparer.Ordinal);
        var lines = Lines(text);
        var index = 0;
        while (index < lines.Length && ids.Count < MaxModels)
        {
            var word = lines[index].Trim();
            index++;
            if (word.Length == 0 || word.Contains(' ') || !IdRx().IsMatch(word) || !word.Contains('/'))
            {
                continue;
            }
            var rest = string.Join("\n", lines.Skip(index).Take(400)).TrimStart();
            var info = rest.StartsWith('{') ? FirstJson(rest) : null;
            if (info is JsonObject obj)
            {
                if (obj["capabilities"] is JsonObject caps && caps["output"] is JsonObject output
                    && output["text"] is JsonNode flag && flag.GetValueKind() == JsonValueKind.False)
                {
                    continue;
                }
                if (obj["cost"] is JsonObject cost && Number(cost["input"]) is double input && Number(cost["output"]) is double outp)
                {
                    prices[word] = [input, outp];
                }
            }
            if (set.Add(word))
            {
                ids.Add(word);
            }
        }
        return (ids, prices);
    }

    private static double? Number(JsonNode? node)
    {
        if (node is JsonValue value && value.GetValueKind() == JsonValueKind.Number && value.TryGetValue<double>(out var d) && d >= 0)
        {
            return d;
        }
        return null;
    }

    /// <summary>The first JSON value at the start of <paramref name="text"/>, ignoring what follows; null when it is not valid.</summary>
    private static JsonNode? FirstJson(string text)
    {
        var bytes = Encoding.UTF8.GetBytes(text);
        try
        {
            var reader = new Utf8JsonReader(bytes, isFinalBlock: true, default);
            while (reader.Read())
            {
                if (reader.CurrentDepth == 0 && reader.TokenType is JsonTokenType.EndObject or JsonTokenType.EndArray)
                {
                    return JsonNode.Parse(bytes.AsSpan(0, (int)reader.BytesConsumed));
                }
            }
        }
        catch (JsonException)
        {
        }
        return null;
    }

    /// <summary>Ids and prices from OpenCode. 1.x prints JSON after <c>--verbose</c>; 2.x lists ids only.</summary>
    public static (List<string> Ids, Dictionary<string, double[]> Prices) ReadOpenCodeCatalog(Func<IReadOnlyList<string>, string> run, string binary)
    {
        string output;
        try
        {
            output = run([binary, "models", "--verbose"]);
        }
        catch (Exception ex) when (CatalogErrors.IsListFailure(ex))
        {
            return (ParseModels(run([binary, "models"])), new Dictionary<string, double[]>());
        }
        var (listed, prices) = ParseVerboseModels(output);
        return listed.Count > 0 ? (listed, prices) : (ParseModels(run([binary, "models"])), new Dictionary<string, double[]>());
    }

    /// <summary>Open Router ids that are free for a limited time (<c>:free</c>, <c>-free</c>, stealth).</summary>
    public static bool IsOpenRouterPromo(string model)
    {
        var text = (model ?? "").ToLowerInvariant();
        if (text.Contains("/stealth/") || text.EndsWith(":free", StringComparison.Ordinal))
        {
            return true;
        }
        return text[(text.LastIndexOf('/') + 1)..].EndsWith("-free", StringComparison.Ordinal);
    }

    /// <summary>
    /// A free OpenCode model: an Open Router promo id, or an OpenCode Zen model at no cost. A price
    /// of zero alone is not enough: Open Router's routers report 0 because they bill whatever model they pick.
    /// </summary>
    public static bool IsFree(string model, IReadOnlyDictionary<string, double[]>? prices = null)
    {
        if (IsOpenRouterPromo(model))
        {
            return true;
        }
        if (!model.StartsWith("opencode/", StringComparison.Ordinal))
        {
            return false;
        }
        return prices is null || !prices.TryGetValue(model, out var price) || !price.Any(p => p != 0);
    }

    /// <summary>What of a CLI's full list is offered as usual: OpenCode keeps its free models only.</summary>
    public static List<string> Offered(string flavor, IReadOnlyList<string> listed, IReadOnlyDictionary<string, double[]>? prices = null) =>
        flavor != "opencode" ? listed.ToList() : listed.Where(m => IsFree(m, prices)).ToList();

    /// <summary>Whether a curated id is still among the CLI's models (Grok's <c>-high</c>/<c>-low</c> are efforts).</summary>
    public static bool IsListed(string flavor, string model, IReadOnlySet<string> listed)
    {
        if (listed.Contains(model) || KeepAlways.Contains(model))
        {
            return true;
        }
        if (flavor == "grok")
        {
            foreach (var suffix in new[] { "-high", "-low" })
            {
                if (model.EndsWith(suffix, StringComparison.Ordinal) && listed.Contains(model[..^suffix.Length]))
                {
                    return true;
                }
            }
        }
        return false;
    }
}
