using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Tests.WebScout;

public sealed class ScoutPolicyTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("scoutpolicy").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    private string Checkout()
    {
        var folder = Path.Combine(_dir, "D3SKWEBSCOUT");
        var python = ScoutLocator.VenvPython(folder);
        Directory.CreateDirectory(Path.GetDirectoryName(python)!);
        File.WriteAllText(python, "");
        Directory.CreateDirectory(Path.Combine(folder, "src", ScoutLocator.Module));
        return folder;
    }

    private static string Value(List<string> args, string flag) => args[args.IndexOf(flag) + 1];

    [Fact]
    [Trait("Security", "P24")]
    public void A_non_live_turn_denies_the_native_tools_and_allows_the_scouts_search_status_and_plain_fetch()
    {
        var args = new ScoutPolicy().CliArgs("claude", isLive: false);

        Assert.Contains("WebSearch", Value(args, "--disallowedTools").Split(','));
        Assert.Contains("WebFetch", Value(args, "--disallowedTools").Split(','));
        Assert.Contains("Bash(*allow-risky*)", Value(args, "--disallowedTools"));
        Assert.Equal(["Bash(d3skwebscout search:*)", "Bash(d3skwebscout status:*)", "Bash(d3skwebscout fetch:*)"], Value(args, "--allowedTools").Split(','));
        Assert.DoesNotContain("--settings", args);
    }

    [Fact]
    [Trait("Security", "P24")]
    public void A_live_turn_asks_before_the_scouts_commands_through_settings_never_an_allow_rule()
    {
        var args = new ScoutPolicy().CliArgs("claude", isLive: true);

        Assert.DoesNotContain("--allowedTools", args);
        var ask = JsonNode.Parse(Value(args, "--settings"))!["permissions"]!["ask"]!.AsArray().Select(n => (string)n!).ToList();
        Assert.Equal(["Bash(d3skwebscout search:*)", "Bash(d3skwebscout status:*)", "Bash(d3skwebscout fetch:*)"], ask);
        Assert.Equal("WebSearch,WebFetch", Value(args, "--disallowedTools"));
    }

    [Fact]
    [Trait("Security", "P24")]
    public void A_live_turn_without_allowed_tools_adds_no_scout_rule_at_all()
    {
        var args = new ScoutPolicy().CliArgs("claude", isLive: true, allowScoutCommands: false);

        Assert.Equal(["--disallowedTools", "WebSearch,WebFetch"], args);
    }

    [Fact]
    public void Combined_keeps_the_built_in_search_and_off_denies_every_way_onto_the_web()
    {
        var combined = new ScoutPolicy(WebMode.Combined).CliArgs("claude", isLive: false);
        Assert.Contains("WebSearch", Value(combined, "--allowedTools").Split(','));
        Assert.StartsWith("WebFetch", Value(combined, "--disallowedTools"), StringComparison.Ordinal);

        var off = new ScoutPolicy(WebMode.Off).CliArgs("claude", isLive: false);
        Assert.Equal(2, off.Count);
        Assert.Contains("mcp__d3skwebscout__fetch", off[1]);
        Assert.Contains("WebSearch", off[1]);
    }

    [Fact]
    public void Another_CLI_is_left_alone()
    {
        var policy = new ScoutPolicy();

        Assert.Empty(policy.CliArgs("cursor", isLive: false));
        Assert.Equal("host text", policy.SystemText("gemini", "host text"));
        var env = new Dictionary<string, string> { ["A"] = "1" };
        Assert.Same(env, policy.MergeEnv("gemini", new Dictionary<string, string>(), env));
    }

    [Fact]
    public void The_briefing_and_the_search_budget_join_the_system_text()
    {
        var text = new ScoutPolicy(maxSearches: 3).SystemText("claude", "host text");

        Assert.StartsWith("host text\n\n", text, StringComparison.Ordinal);
        Assert.Contains("D3SKWEBSCOUT only", text);
        Assert.Contains("at most 3 web searches", text);
        Assert.Equal("host text\n\nmine", new ScoutPolicy(briefing: "mine").SystemText("claude", "host text"));
        Assert.DoesNotContain("budget", new ScoutPolicy(WebMode.Off, maxSearches: 3).SystemText("claude", ""), StringComparison.Ordinal);
    }

    [Fact]
    public void An_unknown_engine_or_a_budget_below_one_is_refused()
    {
        Assert.Throws<ArgumentException>(() => new ScoutPolicy(engine: "altavista"));
        Assert.Throws<ArgumentException>(() => new ScoutPolicy(maxSearches: 0));
    }

    [Fact]
    [Trait("Security", "P24")]
    public void The_scouts_shim_folder_goes_first_on_the_path_and_the_caller_and_engine_are_passed()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "the shim is a POSIX launcher here");
        var shims = Path.Combine(_dir, "shims");
        var policy = new ScoutPolicy(candidates: [Checkout()], caller: "t", engine: "bing", shimFolder: shims);

        var env = policy.MergeEnv("claude", new Dictionary<string, string> { ["PATH"] = "/usr/bin" }, new Dictionary<string, string> { ["KEEP"] = "x" })!;

        Assert.StartsWith(Path.GetFullPath(shims) + Path.PathSeparator, env["PATH"], StringComparison.Ordinal);
        Assert.EndsWith("/usr/bin", env["PATH"], StringComparison.Ordinal);
        Assert.Equal("t", env["WEBSCOUT_CALLER"]);
        Assert.Equal("bing", env["WEBSCOUT_ENGINE"]);
        Assert.Equal("x", env["KEEP"]);
        Assert.True(File.Exists(Path.Combine(shims, ScoutPolicy.Command)));
    }

    [Fact]
    [Trait("Security", "P24")]
    public void Without_a_checkout_nothing_is_added_to_the_environment_and_the_web_stays_denied()
    {
        var policy = new ScoutPolicy(candidates: [Path.Combine(_dir, "nowhere")]);
        var extra = new Dictionary<string, string> { ["KEEP"] = "x" };

        Assert.Same(extra, policy.MergeEnv("claude", new Dictionary<string, string> { ["PATH"] = "/usr/bin" }, extra));
        Assert.Contains("WebSearch", Value(policy.CliArgs("claude", isLive: false), "--disallowedTools"));
    }

    [Fact]
    public void Only_a_plain_scout_fetch_is_approved_by_the_runner_and_never_while_the_web_is_off()
    {
        static ApprovalRequest Ask(string command) => new("r", "c", "Bash", new JsonObject { ["command"] = command });

        var policy = new ScoutPolicy();
        Assert.True(policy.IsScoutFetchApproval(Ask("d3skwebscout fetch https://example.com")));
        Assert.False(policy.IsScoutFetchApproval(Ask("d3skwebscout fetch https://example.com --allow-risky")));
        Assert.False(policy.IsScoutFetchApproval(Ask("d3skwebscout fetch https://example.com --allow")));
        Assert.False(policy.IsScoutFetchApproval(Ask("d3skwebscout fetch https://example.com; id")));
        Assert.False(new ScoutPolicy(WebMode.Off).IsScoutFetchApproval(Ask("d3skwebscout fetch https://example.com")));
    }
}
