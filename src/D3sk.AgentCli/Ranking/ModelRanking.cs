using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Ranking;

/// <summary>Where a model stands: <c>Picker</c> is a CLI's own auto / default setting, <c>Unknown</c> has no rating.</summary>
public enum MetricKind
{
    /// <summary>No rating.</summary>
    Unknown,

    /// <summary>A CLI's own auto / default setting.</summary>
    Picker,

    /// <summary>On the Intelligence Index.</summary>
    Ranked,
}

/// <summary>The rating of one model id.</summary>
public readonly record struct ModelMetrics(MetricKind Kind, int? Intelligence = null, int? Speed = null);

/// <summary>
/// How strong a model is: the Artificial Analysis Intelligence Index and median output speed, from a
/// baseline snapshot overlaid with live figures (a <see cref="MetricsTable"/> the caller fetched and cached).
/// </summary>
public sealed partial class ModelRanking
{
    private static readonly string[] EffortFallback = ["high", "medium", "max", "xhigh", "low"];

    private static readonly Dictionary<string, int> EffortRank = new()
    {
        ["max"] = 5, ["xhigh"] = 4, ["high"] = 3, ["medium"] = 2, ["low"] = 1,
    };

    // Claude Code's short names: opus / sonnet / haiku / fable are not family aliases, this is their only map.
    private static readonly Dictionary<string, string> ClaudeEffortAliases = new()
    {
        ["opus"] = "claude-opus-5-5",
        ["sonnet"] = "claude-sonnet-5-5",
        ["haiku"] = "claude-haiku-5-5",
        ["fable"] = "claude-fable-5-1",
    };

    private static readonly Dictionary<string, string> FamilyAliases = new()
    {
        ["claude-haiku"] = "claude-haiku-4-5",
        ["claude-sonnet"] = "claude-sonnet-5",
        ["gemini-3.1-pro-preview"] = "gemini-3.1-pro",
    };

    private readonly MetricsTable _table;

    /// <summary>The baseline snapshot alone.</summary>
    public ModelRanking()
        : this(null)
    {
    }

    /// <summary>The baseline overlaid with <paramref name="live"/>; live figures win per family and effort.</summary>
    public ModelRanking(MetricsTable? live)
    {
        _table = [];
        foreach (var source in new[] { BuildBaseline(), live ?? [] })
        {
            foreach (var (family, variants) in source)
            {
                var key = CanonicalStem(family);
                if (!_table.TryGetValue(key, out var bucket))
                {
                    _table[key] = bucket = [];
                }

                foreach (var (effort, pair) in variants)
                {
                    bucket[effort] = pair;
                }
            }
        }
    }

    /// <summary>The rating of <paramref name="modelId"/>: ranked, a CLI's own picker, or unknown.</summary>
    public ModelMetrics Metrics(string? modelId)
    {
        var raw = Normalize(modelId ?? "");
        if (raw.Length == 0)
        {
            return new ModelMetrics(MetricKind.Unknown);
        }

        // Open Router's routers (`openrouter/openrouter/auto`) are not a CLI picker.
        if ((raw == "auto" || raw == "default") && !(modelId ?? "").Contains('/'))
        {
            return new ModelMetrics(MetricKind.Picker);
        }

        var (stem, effort) = Parse(raw);
        if (!_table.TryGetValue(Family(stem), out var variants) || variants.Count == 0)
        {
            return new ModelMetrics(MetricKind.Unknown);
        }

        MetricPair chosen;
        if (effort.Length > 0 && variants.TryGetValue(effort, out var exact))
        {
            chosen = exact;
        }
        else
        {
            chosen = EffortFallback.Where(variants.ContainsKey).Select(k => variants[k]).FirstOrDefault(variants.Values.First());
        }

        return new ModelMetrics(MetricKind.Ranked, chosen.Intelligence, chosen.Speed);
    }

    /// <summary>The intelligence index, or null when not ranked (unknown, or a CLI picker).</summary>
    public int? Power(string? modelId) => Metrics(modelId) is { Kind: MetricKind.Ranked } m ? m.Intelligence : null;

    /// <summary>Strongest first; pickers lead, ranked models follow, unknown ones sink and previews last. Ties: speed, effort, then id.</summary>
    public int Compare(string? left, string? right)
    {
        var a = Metrics(left);
        var b = Metrics(right);
        var rank = SortRank(a, left) - SortRank(b, right);
        if (rank != 0)
        {
            return rank;
        }

        if (a.Kind == MetricKind.Ranked)
        {
            var intelligence = (b.Intelligence ?? -1) - (a.Intelligence ?? -1);
            if (intelligence != 0)
            {
                return intelligence;
            }

            var speed = (b.Speed ?? -1) - (a.Speed ?? -1);
            if (speed != 0)
            {
                return speed;
            }

            var effort = EffortOf(right) - EffortOf(left);
            if (effort != 0)
            {
                return effort;
            }
        }

        return string.CompareOrdinal(left ?? "", right ?? "");
    }

    /// <summary>A new list of <paramref name="ids"/> ordered by <see cref="Compare"/>.</summary>
    public List<string> Sort(IEnumerable<string> ids)
    {
        var list = ids.ToList();
        list.Sort(Compare);
        return list;
    }

    /// <summary>"58", or an em dash when unknown.</summary>
    public static string FormatIntelligence(ModelMetrics m) => m.Intelligence is { } i ? i.ToString(CultureInfo.InvariantCulture) : "—";

    /// <summary>"82 t/s", or an em dash when unknown.</summary>
    public static string FormatSpeed(ModelMetrics m) => m.Speed is { } s ? $"{s.ToString(CultureInfo.InvariantCulture)} t/s" : "—";

    /// <summary>The bar width, 0 to 100, or null when either figure is unusable.</summary>
    public static double? BarPercent(double value, double max) =>
        double.IsFinite(value) && double.IsFinite(max) && max > 0 ? Math.Clamp(value / max * 100, 0, 100) : null;

    /// <summary>Extracts the family table from Artificial Analysis's leaderboard: the <c>initialModels</c> array, the Next.js HTML, or its RSC payload.
    /// Non-reasoning duplicates and unranked rows are skipped. Anything else gives an empty table, never an exception.</summary>
    public static MetricsTable ParseLeaderboard(string raw)
    {
        var families = new MetricsTable();
        foreach (var item in FindEntries(raw ?? ""))
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var slug = (Str(item, "slug")).Trim().ToLowerInvariant();
            var idx = Num(item, "intelligenceIndex") ?? Num(item, "intelligence_index");
            if (slug.Length == 0 || idx is null)
            {
                continue;
            }

            var label = (Str(item, "shortName") is { Length: > 0 } s1 ? s1
                : Str(item, "short_name") is { Length: > 0 } s2 ? s2 : Str(item, "name")).Trim();
            if (slug.EndsWith("-non-reasoning", StringComparison.Ordinal)
                || label.Contains("(non-reasoning)", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string family, effort;
            if (SlugEffortRe().Match(slug) is { Success: true } sm)
            {
                family = slug[..sm.Index];
                effort = sm.Groups[1].Value;
            }
            else
            {
                family = slug;
                effort = LabelEffortRe().Match(label) is { Success: true } lm ? lm.Groups[1].Value.ToLowerInvariant() : "high";
            }

            var spd = Num(item, "medianOutputTokensPerSecond");
            if (spd is null && item.TryGetProperty("timescaleData", out var ts) && ts.ValueKind == JsonValueKind.Object)
            {
                spd = Num(ts, "median_output_speed");
            }

            if (!families.TryGetValue(family, out var bucket))
            {
                families[family] = bucket = [];
            }

            bucket.TryAdd(effort, new MetricPair((int)Math.Round(idx.Value), spd is { } sp ? (int)Math.Round(sp) : null));
        }

        return families;
    }

    internal static string Normalize(string modelId)
    {
        var text = modelId.Trim().ToLowerInvariant();
        text = text.EndsWith("[1m]", StringComparison.Ordinal) ? text[..^4] : text;
        text = text[(text.LastIndexOf('/') + 1)..];
        text = text.StartsWith("cursor-", StringComparison.Ordinal) ? text["cursor-".Length..] : text;
        text = text.EndsWith(":free", StringComparison.Ordinal) ? text[..^":free".Length] : text;
        return text.EndsWith("-free", StringComparison.Ordinal) ? text[..^"-free".Length] : text;
    }

    internal static (string Stem, string Effort) Parse(string normalized)
    {
        var stem = normalized.EndsWith("-thinking", StringComparison.Ordinal) ? normalized[..^"-thinking".Length] : normalized;
        if (EffortRe().Match(stem) is { Success: true } m)
        {
            return (stem[..m.Index], m.Groups[1].Value);
        }

        return (stem, "");
    }

    private static int EffortOf(string? id) =>
        EffortRank.GetValueOrDefault(Parse(Normalize(id ?? "")).Effort);

    private static int SortRank(ModelMetrics m, string? id) => m.Kind switch
    {
        MetricKind.Picker => 0,
        MetricKind.Ranked => 1,
        _ => ModelTags.IsPreview(id) ? 3 : 2,
    };

    private static string CanonicalStem(string text) => DigitDotRe().Replace(text, "-");

    // The canonical id for a Claude short name, or the stem when it already is one; null for every other id.
    private static string? ClaudeTarget(string stem)
    {
        if (ClaudeEffortAliases.TryGetValue(stem, out var target))
        {
            return target;
        }

        var canonical = CanonicalStem(stem);
        return ClaudeEffortAliases.ContainsValue(stem) || ClaudeEffortAliases.ContainsValue(canonical) ? stem : null;
    }

    private string Family(string stem)
    {
        if (_table.ContainsKey(stem))
        {
            return stem;
        }

        // A pinned Claude id with no row stays unknown: it must not fall to a shorter family.
        if (ClaudeTarget(stem) is { } pinned)
        {
            if (_table.ContainsKey(pinned))
            {
                return pinned;
            }

            var canon = CanonicalStem(pinned);
            return _table.ContainsKey(canon) ? canon : "";
        }

        if (FamilyAliases.TryGetValue(stem, out var direct) && _table.ContainsKey(direct))
        {
            return direct;
        }

        var cStem = CanonicalStem(stem);
        if (_table.ContainsKey(cStem))
        {
            return cStem;
        }

        foreach (var (alias, target) in FamilyAliases)
        {
            if (CanonicalStem(alias) != cStem)
            {
                continue;
            }

            if (_table.ContainsKey(target))
            {
                return target;
            }

            if (_table.ContainsKey(CanonicalStem(target)))
            {
                return CanonicalStem(target);
            }
        }

        var best = "";
        foreach (var key in _table.Keys)
        {
            var cKey = CanonicalStem(key);
            if ((cStem == cKey || cStem.StartsWith($"{cKey}-", StringComparison.Ordinal)
                    || cKey.StartsWith($"{cStem}-", StringComparison.Ordinal) || cKey.EndsWith($"-{cStem}", StringComparison.Ordinal))
                && key.Length > best.Length)
            {
                best = key;
            }
        }

        return best;
    }

    private static string Str(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    private static double? Num(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && MetricsTable.IsPositiveNumber(v, out var n) ? n : null;

    private static List<JsonElement> FindEntries(string text)
    {
        var result = new List<JsonElement>();
        var trimmed = text.TrimStart();
        if (trimmed.StartsWith('['))
        {
            AddArray(trimmed, 0, result);
            return result;
        }

        var chunks = new StringBuilder();
        foreach (Match m in RscChunkRe().Matches(text))
        {
            try
            {
                using var doc = JsonDocument.Parse(m.Groups[1].Value);
                if (doc.RootElement.ValueKind == JsonValueKind.String)
                {
                    chunks.Append(doc.RootElement.GetString());
                }
            }
            catch (JsonException)
            {
            }
        }

        foreach (var candidate in new[] { chunks.ToString(), text })
        {
            foreach (Match m in ModelsArrayRe().Matches(candidate))
            {
                if (AddArray(candidate, m.Index + m.Length - 1, result))
                {
                    return result;
                }
            }
        }

        return result;
    }

    // Parses one JSON array starting at `start` (the rest of the text may follow it), as Python's raw_decode does.
    private static bool AddArray(string text, int start, List<JsonElement> into)
    {
        try
        {
            var reader = new Utf8JsonReader(Encoding.UTF8.GetBytes(text[start..]));
            if (!reader.Read() || !JsonDocument.TryParseValue(ref reader, out var doc) || doc.RootElement.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            // The document stays alive for the caller to read: entries are cloned out.
            using (doc)
            {
                into.AddRange(doc.RootElement.EnumerateArray().Select(e => e.Clone()));
            }

            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    [GeneratedRegex(@"(?:-thinking)?-(max|xhigh|high|medium|low)$")]
    private static partial Regex EffortRe();

    [GeneratedRegex(@"(?<=\d)\.(?=\d)")]
    private static partial Regex DigitDotRe();

    [GeneratedRegex(@"-(max|xhigh|high|medium|low)$")]
    private static partial Regex SlugEffortRe();

    [GeneratedRegex(@"\((max|xhigh|high|medium|low)\b[^)]*\)$", RegexOptions.IgnoreCase)]
    private static partial Regex LabelEffortRe();

    [GeneratedRegex(@"self\.__next_f\.push\(\[1,(""(?:\\.|[^""\\])*"")\]\)")]
    private static partial Regex RscChunkRe();

    [GeneratedRegex(@"""(?:initialModels|models)""\s*:\s*\[")]
    private static partial Regex ModelsArrayRe();
}
