using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Claude;

public class ClaudeOutputParserTests
{
    private static readonly string[] WrongFields =
    [
        "{\"type\": \"stream_event\", \"event\": \"x\"}",
        "{\"type\": \"stream_event\", \"event\": {\"delta\": 7}}",
        "{\"type\": \"control_response\", \"response\": \"x\"}",
        "{\"type\": \"assistant\", \"message\": \"x\"}",
    ];

    public static TheoryData<string> Captures() => new(
        Directory.GetFiles(StreamCaptures.Folder, "claude__*.jsonl")
            .Where(path => !path.EndsWith(".expected.jsonl", StringComparison.Ordinal))
            .Select(path => Path.GetFileNameWithoutExtension(path)));

    [Fact]
    public void Every_claude_capture_is_covered() => Assert.Equal(3, Captures().Count);

    [Theory]
    [MemberData(nameof(Captures))]
    [Trait("Category", "Preserve")]
    public Task A_recorded_turn_yields_its_expected_events(string name) =>
        StreamCaptures.AssertReplaysAsync(new ClaudeOutputParser(), name, TestContext.Current.CancellationToken);

    [Theory]
    [MemberData(nameof(Captures))]
    [Trait("Category", "Preserve")]
    public Task A_line_that_is_not_the_expected_object_changes_nothing(string name) =>
        StreamCaptures.AssertJunkChangesNothingAsync(
            new ClaudeOutputParser(), name, StreamCaptures.NotObjects.Concat(WrongFields), TestContext.Current.CancellationToken);

    private static Task<List<string>> Parse(ClaudeOutputParser parser, params string[] lines) =>
        StreamCaptures.ParseAsync(parser, string.Join('\n', lines) + "\n", TestContext.Current.CancellationToken);

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_result_text_shows_only_when_no_delta_did()
    {
        var records = await Parse(new ClaudeOutputParser(), "{\"type\":\"result\",\"result\":\"done\"}");
        Assert.Equal(["{\"event\":\"TextDelta\",\"text\":\"done\"}"], records);
        var shown = await Parse(
            new ClaudeOutputParser(),
            "{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"a\"}}}",
            "{\"type\":\"result\",\"result\":\"a\"}");
        Assert.Single(shown);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Tool_calls_and_results_show_only_with_activity()
    {
        var call = "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"t1\",\"name\":\"Bash\",\"input\":{}}]}}";
        var result = "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"tool_use_id\":\"t1\",\"is_error\":true,\"content\":[{\"type\":\"text\",\"text\":\"a\"},{\"type\":\"image\"},{\"type\":\"text\",\"text\":\"b\"}]}]}}";
        Assert.Empty(await Parse(new ClaudeOutputParser(Activity: false), call, result));
        var records = await Parse(new ClaudeOutputParser(), call, result);
        Assert.Equal("{\"event\":\"ToolCall\",\"call_id\":\"t1\",\"name\":\"Bash\",\"arguments\":{}}", records[0]);
        Assert.Contains("\"output\":\"a\\nb\"", records[1]);
        Assert.Contains("\"is_error\":true", records[1]);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Grok_wrapped_tool_results_are_unwrapped()
    {
        Assert.Equal("hi", ClaudeToolText.UnwrapGrok("{\"type\":\"Bash\",\"output\":[27,91,51,49,109,104,105,27,91,48,109]}"));
        Assert.Equal("text", ClaudeToolText.UnwrapGrok("{\"output\":\"text\"}"));
        Assert.Equal("body", ClaudeToolText.UnwrapGrok("{\"type\":\"ReadFile\",\"FileContent\":{\"content\":\"body\"}}"));
        Assert.Equal("{\"x\":1}", ClaudeToolText.UnwrapGrok("{\"x\":1}"));
        Assert.Equal("plain", ClaudeToolText.UnwrapGrok("plain"));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void An_error_result_picks_the_first_readable_text()
    {
        Assert.Equal("boom", Message("{\"result\":\" boom \"}"));
        Assert.Equal("m", Message("{\"result\":{\"error\":\"m\"}}"));
        Assert.Equal("a\nb", Message("{\"errors\":[\"a\",\"\",\"b\"]}"));
        Assert.Equal("The agent reported an error", Message("{}"));

        static string Message(string json) => ClaudeStream.ErrorMessage((System.Text.Json.Nodes.JsonObject)System.Text.Json.Nodes.JsonNode.Parse(json)!);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task The_result_deadline_waits_for_background_agents()
    {
        var changed = "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"local_agent\"},{\"task_type\":\"shell\"}]}";
        var waiting = new TurnDeadline(TimeSpan.FromSeconds(5));
        await Parse(new ClaudeOutputParser(AfterResult: waiting), changed, "{\"type\":\"result\"}");
        Assert.False(waiting.Started);

        var shellOnly = new TurnDeadline(TimeSpan.FromSeconds(5));
        await Parse(
            new ClaudeOutputParser(AfterResult: shellOnly),
            "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"shell\"}]}",
            "{\"type\":\"result\"}");
        Assert.True(shellOnly.Started);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_cancelled_result_adds_the_cancel_note_and_a_repeated_session_id_is_one_event()
    {
        var records = await Parse(
            new ClaudeOutputParser(CancelledMessage: "needs approval"),
            "{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s\"}",
            "{\"type\":\"result\",\"stop_reason\":\"cancelled\",\"session_id\":\"s\"}");
        Assert.Equal(
            ["{\"event\":\"SessionUpdate\",\"session_id\":\"s\"}", "{\"event\":\"StreamError\",\"message\":\"needs approval\",\"code\":\"cancelled\"}"],
            records);
    }
}
