using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Catalog;

/// <summary>One agent CLI as the catalog needs it.</summary>
/// <param name="Command">The CLI's command name (the cache key).</param>
/// <param name="Flavor">Its flavor: claude, cursor, grok, antigravity, opencode, ...</param>
/// <param name="Models">The curated list (specs, or the host's configured models): what a CLI that cannot list offers, and the order of what one that can lists.</param>
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

/// <summary>One agent's merged list: what the CLI offers now (or last time), else its curated list when it cannot list. Ranking is not part of it.</summary>
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
/// <c>grok models</c>, <c>cursor-agent models</c>, <c>opencode models</c>, <c>gemini models</c>,
/// <c>copilot help config</c>) are asked, and only what they list is offered: the curated list only
/// orders it, a listed model the curated list lacks is added and flagged new, a curated model the CLI
/// does not list is dropped. A CLI that fails (offline, signed out) offers the last list it gave, kept
/// on disk; one that never gave a list offers nothing. Claude Code, which cannot list, keeps its
/// curated aliases, or offers what its company gateway lists.
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
        ["gemini"] = ["models", "-o", "json"],
        ["copilot"] = ["help", "config"],
    };

    private readonly string _knownPath;
    private readonly LastReads _lastReads;
    private readonly Func<IReadOnlyList<string>, string> _run;
    private readonly Func<string, IReadOnlyDictionary<string, string>, JsonNode?> _fetch;
    private readonly Func<double> _clock;
    private readonly Dictionary<string, (List<string>? Ids, double ExpiresAt)> _listed = [];
    private readonly Dictionary<string, Dictionary<string, double[]>> _prices = [];
    private readonly Dictionary<string, IReadOnlyDictionary<string, string>> _labels = [];
    private readonly Dictionary<string, HashSet<string>> _toolless = [];
    private readonly Dictionary<string, string> _gateways = [];
    private static readonly IReadOnlyDictionary<string, string> NoHeaders = new Dictionary<string, string>();
    private Dictionary<string, List<string>>? _known;

    /// <param name="knownPath">Where the first read of each catalog is kept (<c>models-known.json</c>).</param>
    /// <param name="run">Runs a CLI's listing; defaults to a real process.</param>
    /// <param name="fetch">Reads a gateway's JSON; defaults to <see cref="CatalogIo.FetchJson(string)"/>.</param>
    /// <param name="clock">Seconds, for the cache.</param>
    public ModelCatalog(
        string knownPath,
        Func<IReadOnlyList<string>, string>? run = null,
        Func<string, JsonNode?>? fetch = null,
        Func<double>? clock = null)
    {
        _knownPath = knownPath;
        _lastReads = new LastReads(LastReads.PathFor(knownPath));
        _run = run ?? CatalogIo.RunList;
        _fetch = fetch is null ? (url, headers) => CatalogIo.FetchJson(url, headers) : (url, _) => fetch(url);
        _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
    }

    /// <summary>
    /// As the first constructor, with a fetch that also takes the headers of the gateway it reads
    /// (empty when none, and always empty for a gateway that is not https).
    /// </summary>
    /// <param name="knownPath">Where the first read of each catalog is kept (<c>models-known.json</c>).</param>
    /// <param name="fetch">Reads a gateway's JSON given its URL and headers.</param>
    /// <param name="run">Runs a CLI's listing; defaults to a real process.</param>
    /// <param name="clock">Seconds, for the cache.</param>
    public ModelCatalog(
        string knownPath,
        Func<string, IReadOnlyDictionary<string, string>, JsonNode?> fetch,
        Func<IReadOnlyList<string>, string>? run = null,
        Func<double>? clock = null)
    {
        _knownPath = knownPath;
        _lastReads = new LastReads(LastReads.PathFor(knownPath));
        _run = run ?? CatalogIo.RunList;
        _fetch = fetch;
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
    public void Refresh(
        IEnumerable<CatalogAgent> agents,
        bool force = false,
        string? claudeGateway = null,
        IReadOnlyDictionary<string, string>? claudeGatewayHeaders = null)
    {
        foreach (var agent in agents)
        {
            if (agent.Flavor == "claude" && agent.Command.Length > 0 && agent.BinaryFound)
            {
                RefreshGateway(agent.Command, claudeGateway, claudeGatewayHeaders, force);
                continue;
            }
            if (agent.Command.Length == 0 || !ListArgs.TryGetValue(agent.Flavor, out var args) || !agent.BinaryFound)
            {
                continue;
            }
            Seed(agent.Command);
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
                switch (agent.Flavor)
                {
                    case "opencode":
                        (listed, prices) = ModelListParser.ReadOpenCodeCatalog(_run, binary);
                        break;
                    case "gemini":
                        listed = ListGemini(binary, args);
                        break;
                    case "copilot":
                        listed = ModelListParser.ParseCopilotModels(_run([binary, .. args]));
                        break;
                    default:
                        listed = ModelListParser.ParseModels(_run([binary, .. args]));
                        break;
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
            _lastReads.Save(agent.Command, listed, prices);
            var offered = ModelListParser.Offered(agent.Flavor, listed);
            if (offered.Count > 0)
            {
                // OpenCode without an Open Router key offers nothing yet: its first real offer is the baseline.
                RememberBaseline(agent.Command, offered);
            }
        }
    }

    /// <summary>The Gemini CLI that lists its models (<c>gemini models</c>, 0.68).</summary>
    public static readonly Version GeminiListsFrom = new(0, 68);

    /// <summary>
    /// <c>gemini models -o json</c>, once <c>gemini --version</c> says it knows that command: an older
    /// CLI takes "models" as a prompt and would spend a model turn on every read.
    /// </summary>
    private List<string> ListGemini(string binary, string[] args)
    {
        var key = Status.ReleaseSources.VersionKey(Status.ReleaseSources.ParseVersion(_run([binary, "--version"])));
        if (key.Count < 2 || key[0] > int.MaxValue || key[1] > int.MaxValue
            || new Version((int)key[0], (int)key[1]) < GeminiListsFrom)
        {
            throw new InvalidOperationException($"this Gemini CLI cannot list its models (needs {GeminiListsFrom} or later)");
        }
        return ModelListParser.ParseGeminiModels(_run([binary, .. args]));
    }

    /// <summary>Whether <paramref name="flavor"/>'s CLI lists its own models (its list is the only one offered).</summary>
    public static bool CanList(string flavor) => ListArgs.ContainsKey(flavor);

    /// <summary>Starts from the list the CLI gave last time, already expired so the CLI is asked again.</summary>
    private void Seed(string command)
    {
        if (_listed.ContainsKey(command) || !_lastReads.TryGet(command, out var ids, out var prices))
        {
            return;
        }
        _listed[command] = (ids, 0);
        _prices[command] = prices;
    }

    private void RefreshGateway(string command, string? baseUrl, IReadOnlyDictionary<string, string>? headers, bool force)
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
            var carried = headers is not null && Uri.TryCreate(baseUrl, UriKind.Absolute, out var gateway) && gateway.Scheme == Uri.UriSchemeHttps;
            found = GatewayModels.Parse(_fetch(GatewayModels.UrlFor(baseUrl), carried ? headers! : NoHeaders));
            if (found.Ids.Count == 0)
            {
                throw new InvalidOperationException("no model ids in the answer");
            }
        }
        catch (Exception ex) when (CatalogErrors.IsListFailure(ex) || ex is HttpRequestException or OperationCanceledException)
        {
            // Not up yet (it may start after the host at login): ask again soon. It said no: later.
            var unreachable = ex is IOException or OperationCanceledException || (ex is HttpRequestException { StatusCode: null });
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

    /// <summary>The merged list for one agent: what its CLI lists, curated ones first, and which of them are new.</summary>
    public MergedModels Merge(CatalogAgent agent)
    {
        var curated = agent.Models.ToList();
        if (CanList(agent.Flavor) && agent.BinaryFound)
        {
            Seed(agent.Command);
        }
        var listed = _listed.TryGetValue(agent.Command, out var cached) ? cached.Ids : null;
        if (listed is null || listed.Count == 0)
        {
            // A CLI that can list but never did (not signed in, offline since install) offers nothing.
            return new MergedModels(CanList(agent.Flavor) ? [] : curated, []);
        }
        if (_gateways.ContainsKey(agent.Command))
        {
            return MergeGateway(agent.Command, curated, listed);
        }
        var prices = _prices.GetValueOrDefault(agent.Command) ?? [];
        var everything = new HashSet<string>(listed, StringComparer.Ordinal);
        var free = ModelListParser.Offered(agent.Flavor, listed);
        var offeredNow = new HashSet<string>(free, StringComparer.Ordinal);
        var kept = curated.Where(m => IsKept(agent.Flavor, m, everything)).ToList();
        var keptSet = new HashSet<string>(kept, StringComparer.Ordinal);
        var baseline = new HashSet<string>(LoadKnown().GetValueOrDefault(agent.Command) ?? [], StringComparer.Ordinal);
        var added = free.Where(m => !keptSet.Contains(m) && !baseline.Contains(m)).ToList();
        var models = kept.Concat(added).ToList();
        var chosen = new HashSet<string>(models, StringComparer.Ordinal);
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

    /// <summary>A curated id the CLI lists, unless the CLI does not offer it (a Zen or paid id under Open Router).</summary>
    private static bool IsKept(string flavor, string model, HashSet<string> listed) =>
        ModelListParser.IsListed(flavor, model, listed)
        && (ModelListParser.KeepAlways.Contains(model) || ModelListParser.Offered(flavor, [model]).Count > 0);

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
