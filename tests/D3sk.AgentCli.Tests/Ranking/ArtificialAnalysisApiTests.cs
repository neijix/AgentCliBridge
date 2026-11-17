using D3sk.AgentCli.Ranking;

namespace D3sk.AgentCli.Tests.Ranking;

public class ArtificialAnalysisApiTests
{
    // Two pages recorded from /api/v2/language/models/free on 2026-11-17, trimmed to the fields read.
    private const string Page1 = """
        {"tier":"free","intelligence_index_version":5,"pagination":{"page":1,"page_size":200,"total_pages":2,"has_more":true},"data":[
        {"id":"593f2d23-247b-41c9-a679-cebd225f0a9a","name":"Claude Fable 5.2 (Max, Default Fallback)","slug":"claude-fable-5-2","release_date":"2026-11-09","evaluations":{"artificial_analysis_intelligence_index":64.6},"performance":{"median_output_tokens_per_second":92.72}},
        {"id":"fdc1913b-9497-45ef-83f7-17dae756f37e","name":"Claude Fable 5.2 (High, Default Fallback)","slug":"claude-fable-5-2-high","release_date":"2026-11-09","evaluations":{"artificial_analysis_intelligence_index":61.8},"performance":{"median_output_tokens_per_second":75.17}},
        {"id":"69468cce-7b5c-414a-b498-41df4c34df85","name":"Beam 1.0","slug":"reflection-beam","release_date":"2026-10-16","evaluations":{"artificial_analysis_intelligence_index":17.7},"performance":{"median_output_tokens_per_second":283.54}},
        {"id":"5720fd2f-873a-4765-8640-a153b38bd64d","name":"DeepSeek V4.1 Flash 1017 (Non-reasoning)","slug":"deepseek-v4-1-flash-1017-non-reasoning","release_date":"2026-10-17","evaluations":{"artificial_analysis_intelligence_index":18.5},"performance":{"median_output_tokens_per_second":172.31}},
        {"id":"dbe7c625-3100-4463-b479-a228c41f75dd","name":"DeepSeek V4.1 Flash (Max)","slug":"deepseek-v4-1-flash","release_date":"2026-09-10","evaluations":{"artificial_analysis_intelligence_index":null},"performance":{"median_output_tokens_per_second":223.14}}]}
        """;

    private const string Page2 = """
        {"tier":"free","intelligence_index_version":5,"pagination":{"page":2,"page_size":200,"total_pages":2,"has_more":false},"data":[
        {"id":"19496b81-9f41-4214-a77a-1df803b3c5ae","name":"GLM-5.3-Flash","slug":"glm-5-3-flash","release_date":"2026-08-26","evaluations":{"artificial_analysis_intelligence_index":27.8},"performance":{"median_output_tokens_per_second":61.27}},
        {"id":"e2c0623e-c855-4a61-bb66-be1f1ed43234","name":"Nemotron 3.5 Super VL","slug":"nemotron-3-5-super-vl","release_date":"2026-10-15","evaluations":{"artificial_analysis_intelligence_index":13.6},"performance":{"median_output_tokens_per_second":276.27}},
        {"id":"f151fd0b-2139-40cf-a3ec-995e8cedc592","name":"DeepSeek V4.1 Flash 1017 (Max)","slug":"deepseek-v4-1-flash-1017","release_date":"2026-10-17","evaluations":{"artificial_analysis_intelligence_index":32.6},"performance":{"median_output_tokens_per_second":168.03}}]}
        """;

    private static MetricsTable ReadBoth(List<int> asked) =>
        ArtificialAnalysisApi.ReadAll(page =>
        {
            asked.Add(page);
            return page == 1 ? Page1 : Page2;
        });

    [Fact]
    public void Reads_every_page_and_keeps_only_ranked_reasoning_rows()
    {
        var asked = new List<int>();
        var t = ReadBoth(asked);
        Assert.Equal([1, 2], asked);
        Assert.Equal(new MetricPair(65, 93), t["claude-fable-5-2"]["max"]);
        Assert.Equal(new MetricPair(62, 75), t["claude-fable-5-2"]["high"]);
        Assert.Equal(new MetricPair(18, 284), t["reflection-beam"]["high"]);
        Assert.Equal(new MetricPair(28, 61), t["glm-5-3-flash"]["high"]);
        Assert.Equal(new MetricPair(33, 168), t["deepseek-v4-1-flash-1017"]["max"]);
        Assert.False(t.ContainsKey("deepseek-v4-1-flash"));
        Assert.Equal(5, t.Count);
    }

    [Theory]
    [InlineData("openrouter/beam-free", 18)]
    [InlineData("openrouter/glm-5.3-flash-free", 28)]
    [InlineData("openrouter/nvidia/nemotron-3.5-super-vl:free", 14)]
    [InlineData("openrouter/nemotron-3.5-super-vl-free", 14)]
    [InlineData("openrouter/deepseek-v4.1-flash-free", 33)]
    [InlineData("claude-fable-5-2-high", 62)]
    public void Live_api_rows_rate_the_open_router_ids(string id, int intelligence)
    {
        var ranking = new ModelRanking(ReadBoth([]));
        Assert.Equal(intelligence, ranking.Metrics(id).Intelligence);
    }

    [Fact]
    public void Stops_at_the_page_cap_and_on_a_page_that_is_not_the_api()
    {
        var calls = 0;
        ArtificialAnalysisApi.ReadAll(_ =>
        {
            calls++;
            return """{"pagination":{"has_more":true},"data":[]}""";
        });
        Assert.Equal(ArtificialAnalysisApi.MaxPages, calls);

        calls = 0;
        Assert.Empty(ArtificialAnalysisApi.ReadAll(_ =>
        {
            calls++;
            return "<html>sign in</html>";
        }));
        Assert.Equal(1, calls);
    }

    [Fact]
    public void Page_request_sends_the_key_in_its_header()
    {
        using var request = ArtificialAnalysisApi.PageRequest(" aa_key123 ", 2);
        Assert.Equal($"{ArtificialAnalysisApi.ModelsUrl}?page=2", request.RequestUri!.ToString());
        Assert.Equal(["aa_key123"], request.Headers.GetValues("x-api-key"));
        Assert.Throws<ArgumentException>(() => ArtificialAnalysisApi.PageRequest("  ", 1));
        Assert.Throws<ArgumentException>(() => ArtificialAnalysisApi.PageRequest("a b", 1));
        Assert.Throws<ArgumentOutOfRangeException>(() => ArtificialAnalysisApi.PageRequest("k", 0));
    }
}
