using D3sk.AgentCli.Catalog;
using D3sk.AgentCli.Ranking;

namespace D3sk.AgentCli.Tests.Ranking;

public class NamesAndTagsTests
{
    private static CatalogAgent Agent(string command, string? flavor = null, string? name = null, string? kind = null, bool prices = false) =>
        new(command, flavor ?? command, [], Name: name, AccountKind: kind, HasPrices: prices);

    [Fact]
    public void Agent_names()
    {
        Assert.Equal("", ModelNames.AgentDisplayName(null));
        Assert.Equal("Open Router", ModelNames.AgentDisplayName(Agent("opencode", name: "OpenCode")));
        Assert.Equal("Claude Code (work)", ModelNames.AgentDisplayName(Agent("claude", name: "Claude Code", kind: "work")));
        Assert.Equal("Claude Code (personal)", ModelNames.AgentDisplayName(Agent("claude", name: "Claude Code", kind: "personal")));
        Assert.Equal("Claude Code", ModelNames.AgentDisplayName(Agent("claude", name: "Claude Code", kind: "other")));
        Assert.Equal("grok", ModelNames.AgentDisplayName(Agent("grok")));
        Assert.Equal("claude::opus", ModelNames.ModelKey("claude", "opus"));
    }

    [Fact]
    public void Model_names()
    {
        var labels = new Dictionary<string, string> { ["opus"] = "Gateway Opus", ["empty"] = "" };
        Assert.Equal("Gateway Opus", ModelNames.ModelDisplayName("opus", labels));
        Assert.Equal("empty", ModelNames.ModelDisplayName("empty", labels));
        Assert.Equal("openrouter/big-pickle", ModelNames.ModelDisplayName("opencode/big-pickle"));
        Assert.Equal("Qwen3-4bit", ModelNames.ModelDisplayName("mlx-community/Qwen3-4bit"));
        Assert.Equal("", ModelNames.ModelDisplayName(null));
        Assert.Equal("sonnet", ModelNames.ModelDisplayName("sonnet"));
    }

    [Theory]
    [InlineData("google/gemma-4-31b-it:free", true)]
    [InlineData("mimo-v2.6-flash-free", true)]
    [InlineData("openrouter/stealth/x", true)]
    [InlineData("opencode/big-pickle", false)]
    [InlineData("free-model/paid", false)]
    public void Limited_free(string id, bool expected)
    {
        Assert.Equal(expected, ModelTags.IsLimitedFree(id));
        Assert.Equal(expected, ModelTags.LimitedNote(id) is not null);
    }

    [Fact]
    public void Free_needs_a_promo_id_or_a_zero_priced_zen_model()
    {
        Assert.True(ModelTags.IsFree("opencode/big-pickle", null));
        Assert.True(ModelTags.IsFree("opencode/big-pickle", [0, 0]));
        Assert.False(ModelTags.IsFree("opencode/paid", [1, 2]));
        Assert.False(ModelTags.IsFree("openrouter/openrouter/auto", [0, 0]));
        Assert.True(ModelTags.IsFree("a:free", [5, 5]));
    }

    [Fact]
    public void Agents()
    {
        Assert.True(ModelTags.IsLocalAgent(Agent("", "mlx")));
        Assert.True(ModelTags.IsLocalAgent(Agent("mlx")));
        Assert.False(ModelTags.IsLocalAgent(Agent("colibri", "colibri")));
        Assert.True(ModelTags.IsPricedAgent(Agent("opencode", "opencode")));
        Assert.True(ModelTags.IsPricedAgent(Agent("claude", "claude", prices: true)));
        Assert.False(ModelTags.IsPricedAgent(Agent("claude", "claude")));
        Assert.False(ModelTags.IsPricedAgent(Agent("mlx", "mlx", prices: true)));
        Assert.False(ModelTags.IsPricedAgent(null));
    }

    [Theory]
    [InlineData(250.4, "$250")]
    [InlineData(15, "$15.00")]
    [InlineData(1.5, "$1.50")]
    [InlineData(0.15, "$0.15")]
    [InlineData(0.5, "$0.5")]
    [InlineData(0.075, "$0.075")]
    [InlineData(0.0012345, "$0.0012")]
    [InlineData(0, "$0")]
    public void Usd(double value, string expected) => Assert.Equal(expected, ModelTags.FormatUsd(value));

    [Fact]
    public void Price_notes()
    {
        Assert.Equal(new PriceNote("Local", "Runs on this computer, no token charge", true), ModelTags.PriceNote("m", null, true, true));
        Assert.Equal(new PriceNote("Plan", "Included in your subscription", false), ModelTags.PriceNote("m", null, false));
        Assert.Equal(new PriceNote("Free", "No cost per token", true), ModelTags.PriceNote("x:free", null));
        var router = ModelTags.PriceNote("openrouter/openrouter/auto", [0, 0]);
        Assert.Equal("—", router.Text);
        Assert.False(router.IsFree);
        Assert.Equal("—", ModelTags.PriceNote("openrouter/m", null).Text);
        var paid = ModelTags.PriceNote("openrouter/m", [3, 15]);
        Assert.Equal("$3.00 / $15.00", paid.Text);
        Assert.Equal("USD per million tokens — input $3.00, output $15.00", paid.Title);
    }

    [Fact]
    public void Preview_and_graduated()
    {
        foreach (var id in new[] { "gemini-3.1-pro-preview", "x/stealth/y", "foo-alpha", "alpha-foo", "space-bunny-free" })
        {
            Assert.True(ModelTags.IsPreview(id), id);
        }

        Assert.False(ModelTags.IsPreview("claude-opus-5-5"));
        Assert.Equal("preview", ModelTags.PreviewNote("x-preview")?.Text);
        Assert.Null(ModelTags.PreviewNote("opus"));
        var r = new ModelRanking();
        Assert.Equal("graduated", ModelTags.IndexNote("openrouter/anthropic/claude-opus-5-5", r)?.Text);
        Assert.Equal("graduated", ModelTags.IndexNote("opencode/gpt-oss-120b", r)?.Text);
        Assert.Null(ModelTags.IndexNote("claude-opus-5-5", r));
        Assert.Null(ModelTags.IndexNote("openrouter/unknown-x", r));
    }
}
