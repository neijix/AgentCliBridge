using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Output.Gemini;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Gemini;

// No tests/streams/gemini__* capture exists yet (recording one needs Gemini installed and signed in), so
// these inline samples stand in; a frozen-capture replay joins them when a capture is recorded.
public class GeminiOutputParserTests
{
    private static readonly string[] Sample =
    [
        "{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"g1\"}",
        "{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"Hel\"}}}",
        "{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"lo\"}}}",
        "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"t1\",\"name\":\"read_file\",\"input\":{}}]}}",
        "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"tool_use_id\":\"t1\",\"content\":\"ok\"}]}}",
        "{\"type\":\"result\",\"result\":\"Hello\",\"session_id\":\"g1\"}",
    ];

    private static readonly string[] WrongFields =
    [
        "{\"type\": \"stream_event\", \"event\": \"x\"}",
        "{\"type\": \"assistant\", \"message\": \"x\"}",
    ];

    private static Task<List<string>> Parse(IEnumerable<string> lines, GeminiOutputParser parser) =>
        StreamCaptures.ParseAsync(parser, string.Join('\n', lines) + "\n", TestContext.Current.CancellationToken);

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Gemini_output_is_claudes_stream_json_event_for_event()
    {
        var gemini = await Parse(Sample, new GeminiOutputParser());
        var claude = await StreamCaptures.ParseAsync(new ClaudeOutputParser(), string.Join('\n', Sample) + "\n", TestContext.Current.CancellationToken);
        Assert.Equal(claude, gemini);
        Assert.Contains("{\"event\":\"SessionUpdate\",\"session_id\":\"g1\"}", gemini);
        Assert.Contains("{\"event\":\"TextDelta\",\"text\":\"Hel\"}", gemini);
        Assert.Contains(gemini, r => r.Contains("\"event\":\"ToolCall\"", StringComparison.Ordinal));
        Assert.Contains(gemini, r => r.Contains("\"event\":\"ToolResult\"", StringComparison.Ordinal));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_cancelled_result_gets_no_cancel_note_of_its_own()
    {
        var records = await Parse(["{\"type\":\"result\",\"stop_reason\":\"cancelled\"}"], new GeminiOutputParser());
        Assert.Empty(records);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_activity_tool_events_are_dropped()
    {
        var records = await Parse(Sample, new GeminiOutputParser(Activity: false));
        Assert.DoesNotContain(records, r => r.Contains("\"event\":\"Tool", StringComparison.Ordinal));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_line_that_is_not_the_expected_object_changes_nothing()
    {
        var expected = await Parse(Sample, new GeminiOutputParser());
        var junk = StreamCaptures.NotObjects.Concat(WrongFields).ToList();
        var noisy = junk.Concat(Sample.Take(1)).Concat(junk).Concat(Sample.Skip(1));
        Assert.Equal(expected, await Parse(noisy, new GeminiOutputParser()));
    }
}
