using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Catalog;

/// <summary>One agent CLI as the catalog needs it.</summary>
/// <param name="Command">The CLI's command name (the cache key).</param>
/// <param name="Flavor">Its flavor: claude, cursor, grok, antigravity, opencode, ...</param>
/// <param name="Models">The curated list (specs, or the host's configured models).</param>
/// <param name="BinaryFound">Whether the binary is installed.</param>
/// <param name="Path">The binary's full path, when known.</param>
/// <param name="Name">The display name (ranking falls back to <paramref name="Command"/>).</param>
/// <param name="AccountKind"><c>personal</c> or <c>work</c> for Claude Code; anything else reads as none.</param>
/// <param name="HasPrices">Whether its models carry prices (a company gateway behind Claude Code).</param>
public sealed record CatalogAgent(
    string Command,
    string Flavor,
    IReadOnlyList<string> Models,
    bool BinaryFound = true,
    string? Path = null,
    string? Name = null,
    string? AccountKind = null,
    bool HasPrices = false);

/// <summary>One agent's merged list: curated plus what the CLI offers now. Ranking is not part of it.</summary>
/// <param name="Models">What to show, optional ones last.</param>
/// <param name="NewModels">Models the CLI lists and nobody has seen yet.</param>
/// <param name="OptionalModels">Models out of the picker until ticked in Settings; null when none.</param>
/// <param name="Prices">Model to [input, output] USD per million tokens; null when none.</param>
/// <param name="Labels">A gateway's display names; null when none.</param>
public sealed record MergedModels(
    IReadOnlyList<string> Models,
    IReadOnlyList<string> NewModels,
    IReadOnlyList<string>? OptionalModels = null,
    IReadOnlyDictionary<string, double[]>? Prices = null,
    IReadOnlyDictionary<string, string>? Labels = null);

/// <summary>
/// Which models each agent CLI offers right now. The CLIs that can list (<c>agy models</c>,
/// <c>grok models</c>, <c>cursor-agent models</c>, <c>opencode models</c>) are asked and their answer
/// merged into the curated list: a listed model the curated list lacks is added and flagged new, a
/// curated model the CLI no longer lists is dropped. A CLI that cannot list, or that fails, keeps the
/// curated list. Claude Code through a company gateway offers what that gateway lists.
/// Results are cached per CLI (an hour; a failure five minutes; a gateway not up yet one minute).
/// </summary>
public sealed class ModelCatalog
{
    /// <summary>How long a successful answer is kept.</summary>
    public const double ListTtl = 60 * 60.0;

    /// <summary>How long a failed read is kept before asking again.</summary>
    public const double FailureTtl = 5 * 60.0;

    /// <summary>A gateway that did not answer may start after the host at login.</summary>
    public const double GatewayRetry = 60.0;

    /// <summary>A first read longer than this is a catalog nobody reviews line by line: it becomes the baseline.</summary>
    public const int Reviewable = 40;

    private static readonly Dictionary<string, string[]> ListArgs = new(StringComparer.Ordinal)
    {
        ["antigravity"] = ["models"],
        ["grok"] = ["models"],
        ["cursor"] = ["models"],
        ["opencode"] = ["models", "--verbose"],
    };

    private readonly string _knownPath;
    private readonly Func<IReadOnlyList<string>, string> _run;
    private readonly Func<string, JsonNode?> _fetch;
    private readonly Func<double> _clock;
    private readonly Dictionary<string, (List<string>? Ids, double ExpiresAt)> _listed = [];
    private readonly Dictionary<string, Dictionary<string, double[]>> _prices = [];
    private readonly Dictionary<string, IReadOnlyDictionary<string, string>> _labels = [];
    private readonly Dictionary<string, HashSet<string>> _toolless = [];
    private readonly Dictionary<string, string> _gateways = [];
    private Dictionary<string, List<string>>? _known;

    /// <param name="knownPath">Where the first read of each catalog is kept (<c>models-known.json</c>).</param>
    /// <param name="run">Runs a CLI's listing; defaults to a real process.</param>
    /// <param name="fetch">Reads a gateway's JSON; defaults to <see cref="CatalogIo.FetchJson"/>.</param>
    /// <param name="clock">Seconds, for the cache.</param>
    public ModelCatalog(
        string knownPath,
        Func<IReadOnlyList<string>, string>? run = null,
        Func<string, JsonNode?>? fetch = null,
        Func<double>? clock = null)
    {
        _knownPath = knownPath;
        _run = run ?? CatalogIo.RunList;
        _fetch = fetch ?? CatalogIo.FetchJson;
        _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
    }

    /// <summary>Reads that CLI's models again next time (it was just updated).</summary>
    public void Forget(string command)
    {
        _listed.Remove(command);
        _prices.Remove(command);
        _labels.Remove(command);
        _toolless.Remove(command);
        _gateways.Remove(command);
    }

    /// <summary>
    /// Asks every CLI that can list its models and whose cached answer expired (blocking).
    /// <paramref name="claudeGateway"/> is the company gateway Claude Code talks to; its list stands for Claude Code's.
    /// </summary>
    public void Refresh(IEnumerable<CatalogAgent> agents, bool force = false, string? claudeGateway = null)
    {
        foreach (var agent in agents)
        {
            if (agent.Flavor == "claude" && agent.Command.Length > 0 && agent.BinaryFound)
            {
                RefreshGateway(agent.Command, claudeGateway, force);
                continue;
            }
            if (agent.Command.Length == 0 || !ListArgs.TryGetValue(agent.Flavor, out var args) || !agent.BinaryFound)
            {
                continue;
            }
            _listed.TryGetValue(agent.Command, out var cached);
            if (cached.ExpiresAt > _clock() && !force && _listed.ContainsKey(agent.Command))
            {
                continue;
            }
            var binary = agent.Path ?? agent.Command;
            var prices = new Dictionary<string, double[]>(StringComparer.Ordinal);
            List<string> listed;
            try
            {
                if (args.Contains("--verbose"))
                {
                    (listed, prices) = ModelListParser.ReadOpenCodeCatalog(_run, binary);
                }
                else
                {
                    listed = ModelListParser.ParseModels(_run([binary, .. args]));
                }
                if (listed.Count == 0)
                {
                    throw new InvalidOperationException("no model ids in the output");
                }
            }
            catch (Exception ex) when (CatalogErrors.IsListFailure(ex))
            {
                _listed[agent.Command] = (cached.Ids, _clock() + FailureTtl);
                continue;
            }
            _listed[agent.Command] = (listed, _clock() + ListTtl);
            _prices[agent.Command] = prices;
            RememberBaseline(agent.Command, ModelListParser.Offered(agent.Flavor, listed, prices));
        }
    }

    private void RefreshGateway(string command, string? baseUrl, bool force)
    {
        if (_gateways.GetValueOrDefault(command) != baseUrl)
        {
            Forget(command); // another gateway, or none any more: the last one's list is not offered
        }
        if (string.IsNullOrEmpty(baseUrl))
        {
            return;
        }
        var has = _listed.TryGetValue(command, out var cached);
        if (has && !force && cached.ExpiresAt > _clock())
        {
            return;
        }
        _gateways[command] = baseUrl;
        GatewayModels found;
        try
        {
            found = GatewayModels.Parse(_fetch(GatewayModels.UrlFor(baseUrl)));
            if (found.Ids.Count == 0)
            {
                throw new InvalidOperationException("no model ids in the answer");
            }
        }
        catch (Exception ex) when (CatalogErrors.IsListFailure(ex) || ex is HttpRequestException)
        {
            // Not up yet (it may start after the host at login): ask again soon. It said no: later.
            var unreachable = ex is IOException || (ex is HttpRequestException { StatusCode: null });
            _listed[command] = (cached.Ids, _clock() + (unreachable ? GatewayRetry : FailureTtl));
            return;
        }
        var toolless = new HashSet<string>(found.Toolless, StringComparer.Ordinal);
        _listed[command] = ([.. found.Ids], _clock() + ListTtl);
        _prices[command] = new Dictionary<string, double[]>(found.Prices, StringComparer.Ordinal);
        _labels[command] = found.Labels;
        _toolless[command] = toolless;
        RememberBaseline(BaselineKey(command), found.Ids.Where(m => !toolless.Contains(m)).ToList(), isCurated: true);
    }

    /// <summary>Where <c>models-known.json</c> keeps a gateway's first read: per gateway, as two companies' lists share nothing.</summary>
    private string BaselineKey(string command) => $"{command}@{HostPort(_gateways.GetValueOrDefault(command, ""))}";

    private static string HostPort(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return "?";
        }
        return uri.IsDefaultPort && !url.Contains($":{uri.Port}", StringComparison.Ordinal) ? uri.Host : $"{uri.Host}:{uri.Port}";
    }

    private Dictionary<string, List<string>> LoadKnown()
    {
        if (_known is not null)
        {
            return _known;
        }
        _known = [];
        try
        {
            if (JsonNode.Parse(File.ReadAllText(_knownPath)) is JsonObject root)
            {
                foreach (var (key, value) in root)
                {
                    if (value is JsonArray array)
                    {
                        _known[key] = array.Select(n => n?.ToString() ?? "").ToList();
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            _known = [];
        }
        return _known;
    }

    private void RememberBaseline(string key, List<string> models, bool isCurated = false)
    {
        var known = LoadKnown();
        if (known.ContainsKey(key))
        {
            return;
        }
        // A list short enough to read is announced model by model; a market is the baseline. A
        // gateway's list is its company's curated list: all of it is.
        known[key] = isCurated || models.Count > Reviewable ? models : [];
        try
        {
            var dir = Path.GetDirectoryName(Path.GetFullPath(_knownPath));
            if (dir is not null)
            {
                Directory.CreateDirectory(dir);
            }
            var root = new JsonObject();
            foreach (var (k, v) in known.OrderBy(p => p.Key, StringComparer.Ordinal))
            {
                root[k] = new JsonArray(v.Select(m => (JsonNode?)JsonValue.Create(m)).ToArray());
            }
            var tmp = Path.ChangeExtension(_knownPath, ".tmp");
            File.WriteAllText(tmp, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            File.Move(tmp, _knownPath, overwrite: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // The baseline stays in memory; it is read again next start.
        }
    }

    /// <summary>The merged list for one agent: curated plus listed, and which of them are new.</summary>
    public MergedModels Merge(CatalogAgent agent)
    {
        var curated = agent.Models.ToList();
        var listed = _listed.TryGetValue(agent.Command, out var cached) ? cached.Ids : null;
        if (listed is null || listed.Count == 0)
        {
            return new MergedModels(curated, []);
        }
        if (_gateways.ContainsKey(agent.Command))
        {
            return MergeGateway(agent.Command, curated, listed);
        }
        var prices = _prices.GetValueOrDefault(agent.Command) ?? [];
        var everything = new HashSet<string>(listed, StringComparer.Ordinal);
        var kept = curated.Where(m => ModelListParser.IsListed(agent.Flavor, m, everything)).ToList();
        var keptSet = new HashSet<string>(kept, StringComparer.Ordinal);
        var baseline = new HashSet<string>(LoadKnown().GetValueOrDefault(agent.Command) ?? [], StringComparer.Ordinal);
        var free = ModelListParser.Offered(agent.Flavor, listed, prices);
        var added = free.Where(m => !keptSet.Contains(m) && !baseline.Contains(m)).ToList();
        var models = kept.Concat(added).ToList();
        if (models.Count == 0)
        {
            models = curated;
        }
        var chosen = new HashSet<string>(models, StringComparer.Ordinal);
        var offeredNow = new HashSet<string>(free, StringComparer.Ordinal);
        // The baseline is not announced, but each of its models can still be ticked in Settings.
        var optional = listed.Where(m => !chosen.Contains(m) && (baseline.Contains(m) || !offeredNow.Contains(m))).ToList();
        if (optional.Count > 0)
        {
            models = models.Concat(optional).ToList();
        }
        List<string>? optionalOut = optional.Count > 0 ? optional : null;
        Dictionary<string, double[]>? pricesOut = null;
        if (prices.Count > 0)
        {
            optionalOut ??= [];
            pricesOut = models.Where(prices.ContainsKey).ToDictionary(m => m, m => prices[m], StringComparer.Ordinal);
        }
        return new MergedModels(models, added, optionalOut, pricesOut);
    }

    private MergedModels MergeGateway(string command, List<string> curated, List<string> listed)
    {
        var toolless = _toolless.GetValueOrDefault(command) ?? [];
        var baseline = new HashSet<string>(LoadKnown().GetValueOrDefault(BaselineKey(command)) ?? [], StringComparer.Ordinal);
        var taken = new HashSet<string>(curated, StringComparer.Ordinal);
        var usable = listed.Where(m => !taken.Contains(m) && !toolless.Contains(m)).ToList();
        var optional = listed.Where(m => !taken.Contains(m) && toolless.Contains(m)).ToList();
        var models = curated.Concat(usable).Concat(optional).ToList();
        var prices = _prices.GetValueOrDefault(command);
        var labels = _labels.GetValueOrDefault(command);
        return new MergedModels(
            models,
            usable.Where(m => !baseline.Contains(m)).ToList(),
            optional.Count > 0 ? optional : null,
            prices is { Count: > 0 } ? models.Where(prices.ContainsKey).ToDictionary(m => m, m => prices[m], StringComparer.Ordinal) : null,
            labels is { Count: > 0 } ? models.Where(labels.ContainsKey).ToDictionary(m => m, m => labels[m], StringComparer.Ordinal) : null);
    }
}
