using System.Net;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Tests.Catalog;

public sealed class ModelCatalogTests : IDisposable
{
    private const string AgyOutput = "Fetching available models...\ngemini-3.8-flash-high\tGemini 3.8 Flash (High)\ngemini-3.7-flash-high\tGemini 3.7 Flash (High)\ngemini-3.1-pro-high\tGemini 3.1 Pro (High)\nclaude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)\n";
    private const string GrokOutput = "You are not authenticated.\n\nDefault model: grok-4.7\n\nAvailable models:\n  * grok-4.7 (default)\n  - grok-4.7-build-fast\n  - grok-4.6\n  - grok-4.5\n";
    private const string Gateway = "http://127.0.0.1:4000";

    private readonly string _dir = Directory.CreateTempSubdirectory("catalog").FullName;
    private double _now = 1000;

    private string Known => Path.Combine(_dir, "known.json");

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    private static CatalogAgent Agent(string command, string flavor, params string[] models) =>
        new(command, flavor, models, true, $"/bin/{command}");

    private ModelCatalog Catalog(Func<IReadOnlyList<string>, string>? run = null, Func<string, JsonNode?>? fetch = null) =>
        new(Known, run, fetch, () => _now);

    [Fact]
    public void Ids_are_read_from_each_cli_s_own_listing()
    {
        Assert.Equal(["gemini-3.8-flash-high", "gemini-3.7-flash-high", "gemini-3.1-pro-high", "claude-opus-4-6-thinking"], ModelListParser.ParseModels(AgyOutput));
        Assert.Equal(["grok-4.7", "grok-4.7-build-fast", "grok-4.6", "grok-4.5"], ModelListParser.ParseModels(GrokOutput));
        Assert.Equal(["openrouter/z-ai/glm-5.2:free", "opencode/big-pickle"],
            ModelListParser.ParseModels("\u001b[1mopenrouter/z-ai/glm-5.2:free\u001b[0m\nopencode/big-pickle\n"));
        Assert.Empty(ModelListParser.ParseModels("Error: Authentication required. Run 'agent login'.\n"));
    }

    [Fact]
    public void Opencode_offers_only_open_router_free_models_and_grok_efforts_count_as_listed()
    {
        string[] listed =
        [
            "openrouter/openai/gpt-6", "openrouter/z-ai/glm-5.2:free", "openrouter/muse-spark-1.3-contributor-free",
            "openrouter/stealth/space-bunny-alpha", "opencode/big-pickle",
        ];
        Assert.Equal(listed[1..4], ModelListParser.Offered("opencode", listed));
        Assert.False(ModelListParser.IsOpenRouterFree("opencode/glm-5.3-flash-free"));
        Assert.Equal(listed, ModelListParser.Offered("grok", listed));
        Assert.True(ModelListParser.IsOpenRouterPromo("openrouter/google/gemma-4-31b-it:free"));
        Assert.False(ModelListParser.IsOpenRouterPromo("opencode/big-pickle"));
        var set = new HashSet<string> { "grok-4.6" };
        Assert.True(ModelListParser.IsListed("grok", "grok-4.6-high", set));
        Assert.False(ModelListParser.IsListed("cursor", "grok-4.6-high", set));
        Assert.True(ModelListParser.IsListed("cursor", "auto", new HashSet<string>()));
    }

    [Fact]
    public void New_models_are_added_and_retired_ones_dropped()
    {
        var catalog = Catalog(argv => argv[0] == "/bin/agy" ? AgyOutput : GrokOutput);
        var agy = Agent("agy", "antigravity", "default", "gemini-3.1-pro-high", "gemini-3.7-flash-high", "gemini-3.1-pro-low");
        var grok = Agent("grok", "grok", "grok-4.6", "grok-4.6-high");
        var claude = Agent("claude", "claude", "sonnet", "opus");
        catalog.Refresh([agy, grok, claude]);

        var merged = catalog.Merge(agy);
        Assert.Equal(["default", "gemini-3.1-pro-high", "gemini-3.7-flash-high", "gemini-3.8-flash-high", "claude-opus-4-6-thinking"], merged.Models);
        Assert.Equal(["gemini-3.8-flash-high", "claude-opus-4-6-thinking"], merged.NewModels);
        var g = catalog.Merge(grok);
        Assert.Equal(["grok-4.6", "grok-4.6-high", "grok-4.7", "grok-4.7-build-fast", "grok-4.5"], g.Models);
        Assert.Equal(["grok-4.7", "grok-4.7-build-fast", "grok-4.5"], g.NewModels);
        Assert.Equal(["sonnet", "opus"], catalog.Merge(claude).Models);
        Assert.Empty(catalog.Merge(claude).NewModels);
    }

    [Fact]
    public void A_long_catalog_is_the_baseline_and_only_later_arrivals_are_new()
    {
        var first = Enumerable.Range(0, ModelCatalog.Reviewable + 10).Select(n => $"model-{n}").ToList();
        var rest = first.Where(m => m != "model-1").ToList();
        var cursor = Agent("agent", "cursor", "auto", "model-1");
        var listing = first;
        Catalog(_ => string.Join('\n', listing)).Refresh([cursor]);
        var one = Catalog(_ => string.Join('\n', listing));
        one.Refresh([cursor]);
        var merged = one.Merge(cursor);
        Assert.Equal(["auto", "model-1", .. rest], merged.Models);
        Assert.Empty(merged.NewModels);
        Assert.Equal(rest, merged.OptionalModels);

        listing = [.. first, "model-99"];
        var later = Catalog(_ => string.Join('\n', listing));
        later.Refresh([cursor]);
        var again = later.Merge(cursor);
        Assert.Equal(["auto", "model-1", "model-99", .. rest], again.Models);
        Assert.Equal(["model-99"], again.NewModels);
        Assert.Equal(first, JsonNode.Parse(File.ReadAllText(Known))!["agent"]!.AsArray().Select(n => n!.ToString()));
    }

    [Fact]
    public void A_cli_that_never_listed_offers_nothing_and_is_retried_later()
    {
        var calls = 0;
        var grok = Agent("grok", "grok", "grok-4.6");
        var catalog = Catalog(_ => { calls++; throw new IOException("not signed in"); });
        Assert.Empty(catalog.Merge(grok).Models);
        catalog.Refresh([grok]);
        catalog.Refresh([grok]);
        Assert.Equal(1, calls);
        Assert.Empty(catalog.Merge(grok).Models);
        _now += 6 * 60;
        catalog.Refresh([grok]);
        Assert.Equal(2, calls);
    }

    [Fact]
    public void A_cli_that_fails_after_a_restart_offers_the_last_list_it_gave()
    {
        var grok = Agent("grok", "grok", "grok-4.6");
        Catalog(_ => GrokOutput).Refresh([grok]);

        var calls = 0;
        var offline = Catalog(_ => { calls++; throw new IOException("offline"); });
        Assert.Equal(["grok-4.6", "grok-4.7", "grok-4.7-build-fast", "grok-4.5"], offline.Merge(grok).Models);
        offline.Refresh([grok]);
        Assert.Equal(1, calls);
        Assert.Equal(["grok-4.6", "grok-4.7", "grok-4.7-build-fast", "grok-4.5"], offline.Merge(grok).Models);

        Assert.Empty(Catalog(_ => throw new IOException("offline")).Merge(grok with { BinaryFound = false }).Models);

        File.WriteAllText(Path.Combine(_dir, "known.listed.json"), "{not json");
        Assert.Empty(Catalog(_ => throw new IOException("offline")).Merge(grok).Models);
    }

    [Fact]
    public void Gemini_and_copilot_list_their_models_and_claude_keeps_its_aliases()
    {
        Assert.Equal(["auto", "gemini-2.5-pro", "gemini-3.5-flash"], ModelListParser.ParseGeminiModels(GeminiJson));
        Assert.Equal(["claude-sonnet-5.5", "claude-fable-5.2", "gpt-6.1-sol", "kimi-k3"], ModelListParser.ParseCopilotModels(CopilotHelpConfig));
        Assert.Empty(ModelListParser.ParseCopilotModels("`logLevel`: level\n    - \"debug\"\n"));

        var calls = new List<string>();
        var geminiVersion = "0.68.2";
        string Run(IReadOnlyList<string> argv)
        {
            calls.Add(string.Join(' ', argv));
            if (argv[0] != "/bin/gemini")
            {
                return CopilotHelpConfig;
            }
            return argv[1] == "--version" ? geminiVersion : GeminiJson;
        }

        var gemini = Agent("gemini", "gemini", "gemini-3.5-flash", "gemini-3.1-pro-preview");
        var copilot = Agent("copilot", "copilot", "auto", "gpt-6.1-sol");
        var claude = Agent("claude", "claude", "sonnet", "opus");

        // Before 0.68 "models" is a prompt: the CLI is never asked, and nothing is offered.
        geminiVersion = "0.67.9";
        var old = new ModelCatalog(Path.Combine(_dir, "old", "known.json"), Run, null, () => _now);
        old.Refresh([gemini]);
        Assert.Equal(["/bin/gemini --version"], calls);
        Assert.Empty(old.Merge(gemini).Models);

        calls.Clear();
        geminiVersion = "0.68.2";
        var catalog = Catalog(Run);
        catalog.Refresh([gemini, copilot, claude]);
        Assert.Equal(["/bin/gemini --version", "/bin/gemini models -o json", "/bin/copilot help config"], calls);
        Assert.Equal(["gemini-3.5-flash", "auto", "gemini-2.5-pro"], catalog.Merge(gemini).Models);
        Assert.Equal(["auto", "gpt-6.1-sol", "claude-sonnet-5.5", "claude-fable-5.2", "kimi-k3"], catalog.Merge(copilot).Models);
        Assert.Equal(["sonnet", "opus"], catalog.Merge(claude).Models);
    }

    [Fact]
    public void Opencode_without_an_open_router_key_offers_no_model_in_the_picker()
    {
        const string zenOnly = "opencode/big-pickle\nopencode/glm-5.3-flash-free\nopencode/beam-free\n";
        var opencode = Agent("opencode", "opencode", "openrouter/google/gemma-4-31b-it:free");
        var catalog = Catalog(argv => argv.Contains("--verbose") ? throw new InvalidOperationException("exit 1") : zenOnly);
        catalog.Refresh([opencode]);
        var merged = catalog.Merge(opencode);
        Assert.Empty(merged.NewModels);
        Assert.Equal(["opencode/big-pickle", "opencode/glm-5.3-flash-free", "opencode/beam-free"], merged.OptionalModels);
        Assert.Equal(merged.OptionalModels, merged.Models);

        // The key comes later: its long free list is the baseline, not a wall of new models.
        var free = Enumerable.Range(0, ModelCatalog.Reviewable + 5).Select(n => $"openrouter/vendor/model-{n}:free");
        var keyed = Catalog(_ => string.Join('\n', free));
        keyed.Refresh([opencode]);
        Assert.Empty(keyed.Merge(opencode).NewModels);
    }

    private const string GeminiJson = """
        Warning: [experimental] a notice before the list
        [
          {"modelId": "auto", "id": "auto", "name": "Auto", "displayName": "Auto",
           "contextLimits": {"inputTokens": 1048576, "outputTokens": 8192}},
          {"modelId": "gemini-2.5-pro", "id": "gemini-2.5-pro", "name": "gemini-2.5-pro"},
          {"modelId": "gemini-3.5-flash", "id": "gemini-3.5-flash"},
          {"id": "--yolo"},
          {"id": 42},
          "not an entry"
        ]
        """;

    private const string CopilotHelpConfig = """
          `logLevel`: logging level.
            - "debug"

          `model`: AI model to use for Copilot CLI, including custom and local models; can be changed with /model command or --model flag option. Refer to `copilot help providers`.
            - "claude-sonnet-5.5"
            - "claude-fable-5.2"
            - "gpt-6.1-sol"
            - "--not-a-model"
            - "kimi-k3"

          `contextTier`: context window tier for tiered-pricing models (e.g., "default" or "long_context").
            - When unset, a model starts on the tier its catalog entry prefers
        """;

    [Fact]
    public void An_answer_is_cached_until_the_cli_is_updated()
    {
        var calls = 0;
        var grok = Agent("grok", "grok", "grok-4.6");
        var catalog = Catalog(_ => { calls++; return GrokOutput; });
        catalog.Refresh([grok]);
        catalog.Refresh([grok]);
        Assert.Equal(1, calls);
        catalog.Forget("grok");
        catalog.Refresh([grok]);
        Assert.Equal(2, calls);
    }

    private const string OpenCodeVerbose = """
        opencode/big-pickle
        {
          "id": "big-pickle",
          "cost": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
          "capabilities": {"output": {"text": true}}
        }
        openrouter/meta/muse-spark-1.3
        {
          "id": "meta/muse-spark-1.3",
          "cost": {"input": 1.25, "output": 4.25},
          "capabilities": {"output": {"text": true}}
        }
        openrouter/qwen/qwen3.8-27b:free
        {
          "cost": {"input": 0, "output": 0}
        }
        openrouter/openrouter/auto
        {
          "cost": {"input": 0, "output": 0}
        }
        openrouter/google/lyria-3-pro
        {
          "cost": {"input": 0, "output": 0},
          "capabilities": {"output": {"text": false, "audio": true}}
        }
        """;

    [Fact]
    public void Opencode_prices_its_models_and_paid_ones_are_optional_not_new()
    {
        var (ids, prices) = ModelListParser.ParseVerboseModels(OpenCodeVerbose);
        Assert.Equal(["opencode/big-pickle", "openrouter/meta/muse-spark-1.3", "openrouter/qwen/qwen3.8-27b:free", "openrouter/openrouter/auto"], ids);
        Assert.Equal([1.25, 4.25], prices["openrouter/meta/muse-spark-1.3"]);
        // A router's price of 0 does not make it free: it bills the model it picks.
        Assert.Equal(["openrouter/qwen/qwen3.8-27b:free"], ModelListParser.Offered("opencode", ids));

        var calls = new List<string>();
        var opencode = Agent("opencode", "opencode", "opencode/big-pickle");
        var catalog = Catalog(argv => { calls.Add(string.Join(' ', argv)); return OpenCodeVerbose; });
        catalog.Refresh([opencode]);
        Assert.Equal(["/bin/opencode models --verbose"], calls);
        var merged = catalog.Merge(opencode);
        // A curated Zen id is listed but not an Open Router free model: optional, not in the picker.
        Assert.Equal(["openrouter/qwen/qwen3.8-27b:free", "opencode/big-pickle", "openrouter/meta/muse-spark-1.3", "openrouter/openrouter/auto"], merged.Models);
        Assert.Equal(["openrouter/qwen/qwen3.8-27b:free"], merged.NewModels);
        Assert.Equal(["opencode/big-pickle", "openrouter/meta/muse-spark-1.3", "openrouter/openrouter/auto"], merged.OptionalModels);
        Assert.Equal([0.0, 0.0], merged.Prices!["opencode/big-pickle"]);
        Assert.DoesNotContain("openrouter/google/lyria-3-pro", merged.Prices.Keys);
    }

    private const string OpenCode2Ids = "opencode/big-pickle\nopencode/muse-spark-1.3-contributor-free\nopenrouter/qwen/qwen3.8-27b:free\nopenrouter/openai/gpt-6\nopenrouter/stealth/space-bunny-alpha\n";

    [Fact]
    public void Opencode_2_lists_free_models_when_verbose_is_gone()
    {
        var calls = new List<string>();
        string Run(IReadOnlyList<string> argv)
        {
            calls.Add(string.Join(' ', argv));
            return argv.Contains("--verbose") ? throw new InvalidOperationException("exit 1: Unrecognized flag: --verbose") : OpenCode2Ids;
        }

        var (ids, prices) = ModelListParser.ReadOpenCodeCatalog(Run, "/bin/opencode");
        Assert.Empty(prices);
        Assert.Contains("openrouter/qwen/qwen3.8-27b:free", ids);
        Assert.Equal(["/bin/opencode models --verbose", "/bin/opencode models"], calls);

        var opencode = Agent("opencode", "opencode", "opencode/big-pickle", "openrouter/stealth/union-alpha");
        var catalog = Catalog(Run);
        catalog.Refresh([opencode]);
        var merged = catalog.Merge(opencode);
        Assert.DoesNotContain("openrouter/stealth/union-alpha", merged.Models);
        Assert.Equal(["openrouter/qwen/qwen3.8-27b:free", "openrouter/stealth/space-bunny-alpha"], merged.NewModels);
        Assert.Equal(["opencode/big-pickle", "opencode/muse-spark-1.3-contributor-free", "openrouter/openai/gpt-6"], merged.OptionalModels);
        Assert.Null(merged.Prices);
    }

    [Fact]
    public void A_verbose_block_of_the_wrong_shape_is_skipped_not_raised()
    {
        const string text = "openrouter/a/one\n{\"capabilities\": [\"text\"], \"cost\": [1, 2]}\n"
            + "openrouter/a/two\n{\"capabilities\": {\"output\": \"text\"}, \"cost\": {\"input\": 1, \"output\": 2}}\n"
            + "openrouter/a/three\n[1, 2]\n";
        var (ids, prices) = ModelListParser.ParseVerboseModels(text);
        Assert.Equal(["openrouter/a/one", "openrouter/a/two", "openrouter/a/three"], ids);
        Assert.Equal(["openrouter/a/two"], prices.Keys);
    }

    private static JsonObject GatewayAnswer() => JsonNode.Parse("""
        {"object": "list", "has_more": false, "data": [
          {"id": "claude-opus-5-5[1m]", "display_name": "Claude Opus 5.5", "type": "chat", "output_modalities": ["text"],
           "capabilities": {"tools": true}, "info": {"input_cost_per_token": 3.0000075e-06, "output_cost_per_token": 1.4999985e-05}},
          {"id": "gateway-gpt-5-5", "display_name": "GPT\n5.5\u0000", "type": "chat", "capabilities": {"tools": true},
           "info": {"input_cost_per_token": 5.00003e-06, "output_cost_per_token": 2.999997e-05}},
          {"id": "sonnet", "display_name": "Claude Sonnet (gateway)", "type": "chat"},
          {"id": "gw-gpt-6-luna", "display_name": "Gw Gpt 6 Luna", "type": "chat", "capabilities": {"tools": false},
           "info": {"input_cost_per_token": 7.5e-08, "output_cost_per_token": 3.75e-07}},
          {"id": "unpriced-model", "display_name": "unpriced-model", "info": {"input_cost_per_token": 0, "output_cost_per_token": 0}},
          {"id": "text-embedding-4", "type": "embedding"},
          {"id": "image-writer", "output_modalities": ["image"]},
          {"id": "--dangerously-skip-permissions", "display_name": "not a model id"},
          {"id": "claude-opus-5-5[1m]", "display_name": "a duplicate"},
          "not an entry"]}
        """)!.AsObject();

    [Fact]
    public void A_gateway_answer_gives_ids_labels_prices_and_the_models_without_tools()
    {
        var found = GatewayModels.Parse(GatewayAnswer());
        Assert.Equal(["claude-opus-5-5[1m]", "gateway-gpt-5-5", "sonnet", "gw-gpt-6-luna", "unpriced-model"], found.Ids);
        Assert.Equal(new Dictionary<string, string>
        {
            ["claude-opus-5-5[1m]"] = "Claude Opus 5.5",
            ["gateway-gpt-5-5"] = "GPT 5.5",
            ["sonnet"] = "Claude Sonnet (gateway)",
            ["gw-gpt-6-luna"] = "Gw Gpt 6 Luna",
        }, found.Labels);
        Assert.Equal([3.0, 15.0], found.Prices["claude-opus-5-5[1m]"]);
        Assert.Equal([5.0, 30.0], found.Prices["gateway-gpt-5-5"]);
        Assert.Equal([0.075, 0.375], found.Prices["gw-gpt-6-luna"]);
        Assert.Equal(3, found.Prices.Count);
        Assert.Equal(["gw-gpt-6-luna"], found.Toolless);
        Assert.Equal(["gpt-6"], GatewayModels.Parse(JsonNode.Parse("""{"data": [{"id": "gpt-6", "object": "model"}]}""")).Ids);
        Assert.Empty(GatewayModels.Parse(JsonNode.Parse("""{"data": "nope"}""")).Ids);
        Assert.Empty(GatewayModels.Parse(JsonNode.Parse("""["claude-opus-5-5"]""")).Ids);
        var long_ = new JsonObject { ["data"] = new JsonArray(new JsonObject { ["id"] = "m1", ["display_name"] = new string('x', 500) }) };
        Assert.Equal(100, GatewayModels.Parse(long_).Labels["m1"].Length);
    }

    [Fact]
    public void Claude_code_through_a_gateway_offers_its_list_and_only_later_arrivals_are_new()
    {
        var answer = GatewayAnswer();
        var urls = new List<string>();
        JsonNode? Fetch(string url) { urls.Add(url); return answer.DeepClone(); }

        var claude = Agent("claude", "claude", "sonnet", "opus");
        var catalog = Catalog(fetch: Fetch);
        catalog.Refresh([claude], claudeGateway: Gateway + "/");
        Assert.Equal(["http://127.0.0.1:4000/v1/models?limit=1000"], urls);
        var merged = catalog.Merge(claude);
        Assert.Equal(["sonnet", "opus", "claude-opus-5-5[1m]", "gateway-gpt-5-5", "unpriced-model", "gw-gpt-6-luna"], merged.Models);
        Assert.Empty(merged.NewModels);
        Assert.Equal(["gw-gpt-6-luna"], merged.OptionalModels);
        Assert.Equal("Claude Sonnet (gateway)", merged.Labels!["sonnet"]);
        Assert.Equal("Claude Opus 5.5", merged.Labels["claude-opus-5-5[1m]"]);
        Assert.Equal([5.0, 30.0], merged.Prices!["gateway-gpt-5-5"]);
        var known = JsonNode.Parse(File.ReadAllText(Known))!["claude@127.0.0.1:4000"]!.AsArray().Select(n => n!.ToString());
        Assert.Equal(["claude-opus-5-5[1m]", "gateway-gpt-5-5", "sonnet", "unpriced-model"], known);

        answer["data"]!.AsArray().Add(JsonNode.Parse("""{"id": "gateway-gemini-3-9-pro", "display_name": "Gemini 3.9 Pro", "type": "chat"}"""));
        var later = Catalog(fetch: Fetch);
        later.Refresh([claude], claudeGateway: Gateway);
        Assert.Equal(["gateway-gemini-3-9-pro"], later.Merge(claude).NewModels);
        Assert.Equal("Gemini 3.9 Pro", later.Merge(claude).Labels!["gateway-gemini-3-9-pro"]);
    }

    [Fact]
    public void Without_a_gateway_or_after_it_is_removed_claude_code_keeps_its_curated_list()
    {
        var urls = new List<string>();
        JsonNode? Fetch(string url) { urls.Add(url); return GatewayAnswer(); }

        var claude = Agent("claude", "claude", "sonnet", "opus");
        var catalog = Catalog(fetch: Fetch);
        catalog.Refresh([claude]);
        Assert.Empty(urls);
        Assert.Equal(["sonnet", "opus"], catalog.Merge(claude).Models);
        catalog.Refresh([claude], claudeGateway: Gateway);
        Assert.Contains("gateway-gpt-5-5", catalog.Merge(claude).Models);
        catalog.Refresh([claude]); // ANTHROPIC_BASE_URL is gone: so is that gateway's list
        Assert.Equal(["sonnet", "opus"], catalog.Merge(claude).Models);
        catalog.Refresh([claude], claudeGateway: "https://ai.example.com/anthropic");
        Assert.Equal("https://ai.example.com/anthropic/v1/models?limit=1000", urls[^1]);
    }

    [Fact]
    public void A_gateway_not_up_yet_is_asked_again_a_minute_later_one_that_refuses_later()
    {
        var calls = 0;
        Exception failure = new HttpRequestException("refused");
        JsonNode? Fetch(string url) { calls++; throw failure; }

        var claude = Agent("claude", "claude", "sonnet");
        var catalog = Catalog(fetch: Fetch);
        catalog.Refresh([claude], claudeGateway: Gateway);
        catalog.Refresh([claude], claudeGateway: Gateway);
        Assert.Equal(1, calls);
        Assert.Equal(["sonnet"], catalog.Merge(claude).Models);
        _now += 61;
        failure = new HttpRequestException("HTTP 401", null, HttpStatusCode.Unauthorized); // wants a token: never sent
        catalog.Refresh([claude], claudeGateway: Gateway);
        Assert.Equal(2, calls);
        _now += 61;
        catalog.Refresh([claude], claudeGateway: Gateway);
        Assert.Equal(2, calls);
        _now += ModelCatalog.FailureTtl;
        catalog.Refresh([claude], claudeGateway: Gateway);
        Assert.Equal(3, calls);
    }

    [Fact]
    public void Only_an_http_url_without_credentials_is_read()
    {
        foreach (var url in new[] { "file:///etc/hosts", "ftp://127.0.0.1/models", "http://user:secret@127.0.0.1:1/v1/models", "not a url" })
        {
            Assert.Throws<ArgumentException>(() => CatalogIo.FetchJson(url));
        }
    }

    [Fact]
    public async Task A_gateway_is_read_without_credentials_a_redirect_is_refused_and_a_huge_answer_stops()
    {
        var (server, number) = LoopbackGateway.StartOnFreePort();
        try
        {
            await ReadThroughGateway(server, number);
        }
        finally
        {
            if (server.IsListening)
            {
                server.Stop(); // once: a second Stop re-binds the port like Close (see CloseStopped)
            }
            LoopbackGateway.CloseStopped(server);
        }
    }

    private static async Task ReadThroughGateway(HttpListener server, int number)
    {
        var seen = new List<(string Path, bool Credentials)>();
        var huge = false;
        var loop = Task.Run(() =>
        {
            while (server.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = server.GetContext(); } catch (Exception) { return; }
                var h = ctx.Request.Headers;
                seen.Add((ctx.Request.Url!.PathAndQuery, h["Authorization"] is not null || h["x-api-key"] is not null || h["Cookie"] is not null));
                try
                {
                    if (ctx.Request.Url.AbsolutePath.StartsWith("/moved"))
                    {
                        ctx.Response.StatusCode = 302;
                        ctx.Response.RedirectLocation = "/v1/models";
                    }
                    else
                    {
                        ctx.Response.ContentType = "application/json";
                        var body = huge ? new byte[CatalogIo.GatewayMaxBytes + 1] : System.Text.Encoding.UTF8.GetBytes(GatewayAnswer().ToJsonString());
                        ctx.Response.OutputStream.Write(body);
                    }
                    ctx.Response.Close();
                }
                catch (Exception ex) when (ex is HttpListenerException or IOException or ObjectDisposedException or InvalidOperationException)
                {
                    try { ctx.Response.Abort(); } catch (ObjectDisposedException) { } // the client gave up at the size limit
                }
            }
        }, TestContext.Current.CancellationToken);
        var baseUrl = $"http://127.0.0.1:{number}";
        var node = CatalogIo.FetchJson($"{baseUrl}/v1/models?limit=1000");
        Assert.Equal("claude-opus-5-5[1m]", node!["data"]![0]!["id"]!.ToString());
        Assert.Equal(("/v1/models?limit=1000", false), seen[0]);
        var redirect = Assert.Throws<HttpRequestException>(() => CatalogIo.FetchJson($"{baseUrl}/moved"));
        Assert.Equal(HttpStatusCode.Found, redirect.StatusCode);
        Assert.Equal(["/v1/models?limit=1000", "/moved"], seen.Select(s => s.Path)); // never followed
        huge = true;
        Assert.Contains("over", Assert.Throws<ArgumentException>(() => CatalogIo.FetchJson($"{baseUrl}/v1/models")).Message);
        server.Stop();
        await loop.WaitAsync(TimeSpan.FromSeconds(30), TestContext.Current.CancellationToken); // a write stuck on a gone client fails, never hangs
    }
}
