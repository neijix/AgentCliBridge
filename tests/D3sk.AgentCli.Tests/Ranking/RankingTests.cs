using D3sk.AgentCli.Ranking;

namespace D3sk.AgentCli.Tests.Ranking;

public class RankingTests
{
    private readonly ModelRanking _r = new();

    [Theory]
    [InlineData("claude-opus-5-5-high", 54, 82)]
    [InlineData("claude-opus-5-5[1m]", 54, 82)]
    [InlineData("opus", 54, 82)]
    [InlineData("cursor-gpt-6-sol-max", 48, 86)]
    [InlineData("openrouter/google/gemma-4-31b-it:free", 19, 35)]
    [InlineData("gemini-3.1-pro-preview", 30, 119)]
    [InlineData("gemini-3.8-flash-low", 33, null)]
    public void Ranks_known_ids(string id, int intelligence, int? speed)
    {
        var m = _r.Metrics(id);
        Assert.Equal(MetricKind.Ranked, m.Kind);
        Assert.Equal(intelligence, m.Intelligence);
        Assert.Equal(speed, m.Speed);
    }

    [Fact]
    public void Pickers_and_unknowns()
    {
        Assert.Equal(MetricKind.Picker, _r.Metrics("auto").Kind);
        Assert.Equal(MetricKind.Picker, _r.Metrics("default").Kind);
        Assert.Equal(MetricKind.Unknown, _r.Metrics("openrouter/openrouter/auto").Kind);
        Assert.Equal(MetricKind.Unknown, _r.Metrics("").Kind);
        Assert.Equal(MetricKind.Unknown, _r.Metrics(null).Kind);
        Assert.Null(_r.Power("auto"));
        Assert.Null(_r.Power("zzz-9"));
        Assert.Equal(54, _r.Power("claude-opus-5-5"));
    }

    [Fact]
    public void An_unlisted_id_takes_the_longest_matching_family()
    {
        Assert.Equal(51, _r.Power("claude-opus-5-6"));
        Assert.Equal(39, _r.Power("claude-opus-4-6-high"));
        Assert.Equal(32, _r.Power("claude-sonnet-high"));
    }

    [Fact]
    public void Live_figures_overlay_the_baseline()
    {
        var live = MetricsTable.Sanitize("""{"claude-opus-5-5":{"high":[70,90]},"brand-new":{"high":[61.4,12.6]}}""");
        var r = new ModelRanking(live);
        Assert.Equal(70, r.Metrics("claude-opus-5-5-high").Intelligence);
        Assert.Equal(51, r.Metrics("claude-opus-5-5-medium").Intelligence);
        Assert.Equal(new ModelMetrics(MetricKind.Ranked, 61, 13), r.Metrics("brand-new"));
    }

    [Fact]
    public void Sanitize_drops_bad_shapes()
    {
        var t = MetricsTable.Sanitize("""{"a":{"high":[0,5],"low":[-1],"x":"s"},"b":{"high":[10,"fast"],"max":[true,3]},"":{"high":[1,1]},"c":5}""");
        Assert.Single(t);
        Assert.Equal(new MetricPair(10, null), t["b"]["high"]);
        Assert.Empty(MetricsTable.Sanitize("not json"));
        Assert.Empty(MetricsTable.Sanitize("[1]"));
    }

    [Fact]
    public void Sorts_pickers_then_ranked_then_unknown_then_previews()
    {
        var sorted = _r.Sort(["zzz-preview", "unknown-b", "claude-haiku-4-5", "auto", "claude-opus-5-5", "unknown-a"]);
        Assert.Equal(["auto", "claude-opus-5-5", "claude-haiku-4-5", "unknown-a", "unknown-b", "zzz-preview"], sorted);
    }

    [Fact]
    public void Ties_break_on_speed_then_effort()
    {
        // grok-4.7 xhigh [46,82] vs high [46,83]: faster first.
        Assert.Equal(["grok-4.7-high", "grok-4.7-xhigh"], _r.Sort(["grok-4.7-xhigh", "grok-4.7-high"]));
        // gpt-5.6-sol max and high are both [47,96]: higher effort first.
        Assert.Equal(["gpt-5.6-sol-max", "gpt-5.6-sol-high"], _r.Sort(["gpt-5.6-sol-high", "gpt-5.6-sol-max"]));
    }

    [Fact]
    public void Formats()
    {
        Assert.Equal("54", ModelRanking.FormatIntelligence(_r.Metrics("opus")));
        Assert.Equal("—", ModelRanking.FormatIntelligence(_r.Metrics("nope")));
        Assert.Equal("82 t/s", ModelRanking.FormatSpeed(_r.Metrics("opus")));
        Assert.Equal("—", ModelRanking.FormatSpeed(_r.Metrics("claude-opus-5-5-max")));
        Assert.Equal(50, ModelRanking.BarPercent(5, 10));
        Assert.Equal(100, ModelRanking.BarPercent(50, 10));
        Assert.Null(ModelRanking.BarPercent(5, 0));
    }

    [Fact]
    public void Parses_an_initialModels_array_and_skips_non_reasoning()
    {
        const string json = """
            [{"slug":"foo-x-high","intelligenceIndex":50.4,"medianOutputTokensPerSecond":100.5},
             {"slug":"foo-x-low","intelligenceIndex":40,"timescaleData":{"median_output_speed":70}},
             {"slug":"bar","shortName":"Bar (max)","intelligence_index":33},
             {"slug":"baz","name":"Baz","intelligenceIndex":20},
             {"slug":"foo-x-non-reasoning","intelligenceIndex":9},
             {"slug":"qux","name":"Qux (Non-reasoning)","intelligenceIndex":9},
             {"slug":"none"}, 5]
            """;
        var t = ModelRanking.ParseLeaderboard(json);
        Assert.Equal(new MetricPair(50, 100), t["foo-x"]["high"]);
        Assert.Equal(new MetricPair(40, 70), t["foo-x"]["low"]);
        Assert.Equal(new MetricPair(33, null), t["bar"]["max"]);
        Assert.Equal(new MetricPair(20, null), t["baz"]["high"]);
        Assert.False(t.ContainsKey("qux"));
        Assert.Equal(3, t.Count);
    }

    [Fact]
    public void Parses_the_nextjs_payload()
    {
        var chunk = System.Text.Json.JsonSerializer.Serialize("""x:{"initialModels":[{"slug":"m-high","intelligenceIndex":12}]} tail""");
        var page = $"<html><script>self.__next_f.push([1,{chunk}])</script></html>";
        Assert.Equal(new MetricPair(12, null), ModelRanking.ParseLeaderboard(page)["m"]["high"]);
        var plain = """<script>{"models":[{"slug":"p","intelligenceIndex":7}],"x":1}</script>""";
        Assert.Equal(new MetricPair(7, null), ModelRanking.ParseLeaderboard(plain)["p"]["high"]);
        Assert.Empty(ModelRanking.ParseLeaderboard("<html>nothing</html>"));
        Assert.Empty(ModelRanking.ParseLeaderboard(""));
    }
}
