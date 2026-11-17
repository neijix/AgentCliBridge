using System.Text.Json;

namespace D3sk.AgentCli.Ranking;

/// <summary>
/// Artificial Analysis's data API v2 model list (<c>/api/v2/language/models/free</c>): every key tier may call it,
/// 100 calls a day on the free one. Its terms ask that a host showing the figures credits Artificial Analysis.
/// The transport is the host's; this builds the requests and reads the pages.
/// </summary>
public static class ArtificialAnalysisApi
{
    /// <summary>The free-tier model list, one page of up to 200 models per call.</summary>
    public const string ModelsUrl = "https://artificialanalysis.ai/api/v2/language/models/free";

    /// <summary>The environment variable a host may read the API key from.</summary>
    public const string KeyEnv = "ARTIFICIAL_ANALYSIS_API_KEY";

    /// <summary>The most pages read in one refresh, whatever the API says is left.</summary>
    public const int MaxPages = 10;

    /// <summary>A GET of page <paramref name="page"/> (from 1) authenticated with <paramref name="apiKey"/> in <c>x-api-key</c>.</summary>
    public static HttpRequestMessage PageRequest(string apiKey, int page)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(page, 1);
        var key = (apiKey ?? "").Trim();
        if (key.Length == 0 || key.Any(char.IsControl) || key.Any(char.IsWhiteSpace))
        {
            throw new ArgumentException("the Artificial Analysis API key is empty or malformed", nameof(apiKey));
        }

        var request = new HttpRequestMessage(HttpMethod.Get, $"{ModelsUrl}?page={page}");
        request.Headers.TryAddWithoutValidation("x-api-key", key);
        request.Headers.Accept.ParseAdd("application/json");
        return request;
    }

    /// <summary>
    /// Reads pages 1, 2, … through <paramref name="fetchPage"/> while the API says more are left (at most
    /// <see cref="MaxPages"/>) and merges their rows into one table; the first row of a family and effort wins.
    /// A page that is not an API page stops the reading. Whatever <paramref name="fetchPage"/> throws propagates.
    /// </summary>
    public static MetricsTable ReadAll(Func<int, string> fetchPage)
    {
        ArgumentNullException.ThrowIfNull(fetchPage);
        var merged = new MetricsTable();
        for (var page = 1; page <= MaxPages; page++)
        {
            var raw = fetchPage(page) ?? "";
            foreach (var (family, variants) in ModelRanking.ParseLeaderboard(raw))
            {
                if (!merged.TryGetValue(family, out var bucket))
                {
                    merged[family] = bucket = [];
                }

                foreach (var (effort, pair) in variants)
                {
                    bucket.TryAdd(effort, pair);
                }
            }

            if (!HasMore(raw))
            {
                break;
            }
        }

        return merged;
    }

    private static bool HasMore(string raw)
    {
        try
        {
            using var doc = JsonDocument.Parse(raw);
            return doc.RootElement.ValueKind == JsonValueKind.Object
                && doc.RootElement.TryGetProperty("pagination", out var p) && p.ValueKind == JsonValueKind.Object
                && p.TryGetProperty("has_more", out var more) && more.ValueKind == JsonValueKind.True;
        }
        catch (JsonException)
        {
            return false;
        }
    }
}
