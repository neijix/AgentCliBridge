using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.OpenCode;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.OpenCode;

[Trait("Preserve", "streams")]
public class OpenCodeOutputParserTests
{
    private static readonly string[] WrongFields = ["""{"type": "text", "part": "x"}"""];

    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    private static async Task<List<StreamEvent>> Events(string stdout, bool activity = true)
    {
        var records = new List<StreamEvent>();
        await foreach (var e in new OpenCodeOutputParser(activity).ParseAsync(ToLines(stdout), Ct)) records.Add(e);
        return records;
    }

    private static async IAsyncEnumerable<D3sk.AgentCli.Runner.ChildLine> ToLines(string stdout)
    {
        foreach (var line in stdout.Split('\n')) yield return new D3sk.AgentCli.Runner.ChildLine(System.Text.Encoding.UTF8.GetBytes(line));
        await Task.CompletedTask;
    }

    [Theory]
    [InlineData("opencode__provider_error")]
    [InlineData("opencode__reasoning_tools_paragraphs")]
    public async Task A_recorded_turn_yields_its_expected_events(string name) =>
        await StreamCaptures.AssertReplaysAsync(new OpenCodeOutputParser(), name, Ct);

    [Theory]
    [InlineData("opencode__provider_error")]
    [InlineData("opencode__reasoning_tools_paragraphs")]
    public async Task A_line_that_is_not_the_expected_object_changes_nothing(string name) =>
        await StreamCaptures.AssertJunkChangesNothingAsync(new OpenCodeOutputParser(), name, StreamCaptures.NotObjects.Concat(WrongFields), Ct);

    [Fact]
    public async Task Without_activity_only_text_and_errors_remain()
    {
        var events = await Events(StreamCaptures.Capture("opencode__reasoning_tools_paragraphs"), activity: false);
        Assert.Equal([new SessionUpdate("ses_1"), new TextDelta("It says hello."), new TextDelta("\n\nDone.")], events);
    }

    [Fact]
    public async Task A_running_tool_is_only_the_call_and_is_not_repeated()
    {
        var running = """{"type":"tool_use","sessionID":"s","part":{"tool":"bash","callID":"c","state":{"status":"running","input":{"a":1}}}}""";
        var done = """{"type":"tool_use","sessionID":"s","part":{"tool":"bash","callID":"c","state":{"status":"completed","output":"ok"}}}""";
        var events = await Events(running + "\n" + done);
        Assert.Equal(3, events.Count);
        Assert.IsType<ToolCall>(events[1]);
        Assert.Equal(new ToolResult("c", "ok", false), events[2]);
    }

    [Fact]
    public async Task An_error_without_a_message_names_itself_with_its_data()
    {
        var events = await Events("""{"type":"error","error":{"name":"APIError","data":{"statusCode":400,"x":"é"}}}""");
        Assert.Equal(new StreamError("APIError: {\"statusCode\": 400, \"x\": \"é\"}", "agent_error"), events.Single());
        events = await Events("""{"type":"error"}""");
        Assert.Equal("Open Router error", ((StreamError)events.Single()).Message);
    }
}
