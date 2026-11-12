using System.Text.Json.Nodes;
using D3sk.AgentCli.Output.Cursor;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Cursor;

public class CursorParserTests
{
    private static readonly string[] WrongFields =
    [
        "{\"type\": \"assistant\", \"message\": \"x\"}",
        "{\"type\": \"tool_call\", \"tool_call\": \"x\"}",
    ];

    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    private static async Task<List<JsonNode>> Parse(CursorParser parser, params string[] lines) =>
        (await StreamCaptures.ParseAsync(parser, string.Join('\n', lines) + "\n", Ct)).Select(r => JsonNode.Parse(r)!).ToList();

    [Fact]
    [Trait("Category", "Preserve")]
    public Task A_recorded_turn_yields_its_expected_events() =>
        StreamCaptures.AssertReplaysAsync(new CursorParser(), "agent__thinking_tools_text", Ct);

    [Fact]
    [Trait("Category", "Preserve")]
    public Task A_line_that_is_not_the_expected_object_changes_nothing() =>
        StreamCaptures.AssertJunkChangesNothingAsync(
            new CursorParser(), "agent__thinking_tools_text", StreamCaptures.NotObjects.Concat(WrongFields), Ct);

    [Fact]
    public void Every_cursor_capture_is_covered() =>
        Assert.Single(Directory.GetFiles(StreamCaptures.Folder, "agent__*.jsonl"), p => !p.EndsWith(".expected.jsonl", StringComparison.Ordinal));

    [Fact]
    [Trait("Category", "Preserve")]
    public void Only_a_real_time_delta_is_text()
    {
        var delta = JsonNode.Parse("{\"type\":\"assistant\",\"timestamp_ms\":1,\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"Hello\"}]}}")!.AsObject();
        var flush = JsonNode.Parse("{\"type\":\"assistant\",\"timestamp_ms\":1,\"model_call_id\":\"x\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"Hello\"}]}}")!.AsObject();
        Assert.Equal("Hello", CursorParser.ExtractText(delta));
        Assert.Equal("", CursorParser.ExtractText(flush));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Activity_off_keeps_only_text_and_session()
    {
        var events = await Parse(new CursorParser(Activity: false),
            "{\"type\":\"thinking\",\"subtype\":\"delta\",\"text\":\"t\"}",
            "{\"type\":\"tool_call\",\"subtype\":\"started\",\"call_id\":\"k\",\"tool_call\":{\"shellToolCall\":{\"args\":{}}}}");
        Assert.Empty(events);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_failed_result_is_an_agent_error_and_a_result_text_shows_only_when_no_delta_did()
    {
        var error = await Parse(new CursorParser(), "{\"type\":\"result\",\"is_error\":true,\"result\":\"Failed to authenticate\"}");
        Assert.Equal("StreamError", error[0]["event"]!.GetValue<string>());
        Assert.Equal("agent_error", error[0]["code"]!.GetValue<string>());
        var text = await Parse(new CursorParser(), "{\"type\":\"result\",\"result\":\"Hi\"}");
        Assert.Equal("Hi", text[0]["text"]!.GetValue<string>());
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_failed_tool_result_and_non_plain_arguments()
    {
        var events = await Parse(new CursorParser(),
            "{\"type\":\"tool_call\",\"subtype\":\"started\",\"call_id\":\"k\",\"tool_call\":{\"readToolCall\":{\"args\":{\"path\":\"a\",\"n\":0,\"toolCallId\":\"z\",\"empty\":\"\",\"nest\":{\"x\":1}}}}}",
            "{\"type\":\"tool_call\",\"subtype\":\"completed\",\"call_id\":\"k\",\"tool_call\":{\"readToolCall\":{\"result\":{\"error\":{\"message\":\"nope\"}}}}}");
        Assert.Equal("{\"path\":\"a\",\"n\":0}", events[0]["arguments"]!.ToJsonString());
        Assert.Equal("nope", events[1]["output"]!.GetValue<string>());
        Assert.True(events[1]["is_error"]!.GetValue<bool>());
    }
}
