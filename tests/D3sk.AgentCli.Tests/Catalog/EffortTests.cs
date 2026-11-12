using System.Text.Json.Nodes;
using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Tests.Catalog;

public class EffortTests
{
    [Fact]
    public void Claude_gets_effort_and_ultracode_flags()
    {
        var args = Effort.Args("claude", "max", true);
        Assert.Equal(["--effort", "max", "--settings"], args.Take(3));
        Assert.True(JsonNode.Parse(args[3])!["ultracode"]!.GetValue<bool>());
    }

    [Fact]
    public void Auto_or_missing_values_pass_nothing()
    {
        Assert.Empty(Effort.Args("claude"));
        Assert.Empty(Effort.Args("claude", "auto", false));
    }

    [Fact]
    public void Ultracode_alone_passes_only_the_setting()
    {
        Assert.Equal(["--settings", Effort.UltracodeSettings], Effort.Args("claude", null, true));
    }

    [Fact]
    public void An_unknown_effort_never_becomes_an_argument()
    {
        Assert.Empty(Effort.Args("claude", "--dangerously-skip-permissions"));
        Assert.Empty(Effort.Args("copilot", "max"));
    }

    [Fact]
    public void Copilot_gets_reasoning_effort_only()
    {
        Assert.Equal(["--reasoning-effort", "high"], Effort.Args("copilot", "high", true));
    }

    [Theory]
    [InlineData("cursor")]
    [InlineData("gemini")]
    [InlineData("grok")]
    [InlineData("opencode")]
    [InlineData("antigravity")]
    public void Other_clis_get_nothing(string flavor) => Assert.Empty(Effort.Args(flavor, "high", true));

    [Fact]
    public void A_claude_model_without_effort_gets_neither_flag()
    {
        Assert.Empty(Effort.Args("claude", "high", true, "claude-sonnet-4-5-20250929"));
        Assert.Empty(Effort.Args("claude", "max", true, "us.anthropic.claude-opus-4-1-v1:0"));
    }

    [Fact]
    public void A_level_the_model_lacks_runs_as_the_strongest_below_it()
    {
        Assert.Equal(["--effort", "high"], Effort.Args("claude", "max", false, "claude-opus-4-5"));
        Assert.Equal(["--effort", "high"], Effort.Args("claude", "xhigh", false, "claude-opus-4-6"));
        Assert.Equal(["--effort", "max"], Effort.Args("claude", "max", false, "opus"));
        Assert.Equal(["--effort", "xhigh"], Effort.Args("claude", "xhigh", false, "claude-opus-6"));
    }

    [Fact]
    public void Ultracode_never_goes_to_haiku()
    {
        Assert.Equal(["--effort", "low"], Effort.Args("claude", "low", true, "haiku"));
        Assert.Equal("--settings", Effort.Args("claude", "auto", true, "claude-opus-5-5[1m]")[0]);
    }

    [Theory]
    [InlineData("", "low,medium,high,xhigh,max")]
    [InlineData("opus", "low,medium,high,xhigh,max")]
    [InlineData("claude-opus-5-5[1m]", "low,medium,high,xhigh,max")]
    [InlineData("claude-opus-4-7", "low,medium,high,xhigh,max")]
    [InlineData("claude-opus-4-6", "low,medium,high,max")]
    [InlineData("claude-opus-4-5-20251101", "low,medium,high")]
    [InlineData("claude-sonnet-4-6", "low,medium,high,max")]
    [InlineData("us.anthropic.claude-opus-4-6-v1", "low,medium,high,max")]
    [InlineData("anthropic/claude-opus-4-5", "low,medium,high")]
    [InlineData("claude-mythos-5-1", "low,medium,high,xhigh,max")]
    [InlineData("claude-sonnet-4", null)]
    [InlineData("claude-sonnet-4-5", null)]
    [InlineData("claude-opus-4-1@20250805", null)]
    [InlineData("claude-haiku-4-5-20251001", null)]
    [InlineData("claude-3-7-sonnet", null)]
    [InlineData("claude-mythos-5", null)]
    [InlineData("us.anthropic.claude-sonnet-4-5-20250929-v1:0", null)]
    public void The_levels_table(string model, string? levels)
    {
        var got = Effort.ClaudeLevels(model);
        Assert.Equal(levels, got is null ? null : string.Join(',', got));
    }
}
