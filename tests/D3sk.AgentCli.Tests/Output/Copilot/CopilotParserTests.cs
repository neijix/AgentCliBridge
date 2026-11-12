using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Copilot;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Copilot;

public class CopilotParserTests
{
    private static readonly string[] WrongFields = ["{\"type\": \"assistant.message_delta\", \"data\": \"x\"}"];

    [Fact]
    public async Task Capture_replays()
    {
        var status = new CopilotStatus();
        await StreamCaptures.AssertReplaysAsync(new CopilotParser(true, status), "copilot__reasoning_tools_text", TestContext.Current.CancellationToken);
        Assert.Equal(0, status.ResultExit);
    }

    [Fact]
    public async Task Junk_changes_nothing()
    {
        await StreamCaptures.AssertJunkChangesNothingAsync(
            new CopilotParser(), "copilot__reasoning_tools_text", StreamCaptures.NotObjects.Concat(WrongFields), TestContext.Current.CancellationToken);
    }

    [Fact]
    public async Task Without_activity_only_text_and_session_remain()
    {
        var records = await StreamCaptures.ParseAsync(new CopilotParser(false), StreamCaptures.Capture("copilot__reasoning_tools_text"), TestContext.Current.CancellationToken);
        Assert.DoesNotContain(records, r => r.Contains("ThinkingDelta") || r.Contains("Tool"));
        Assert.Contains(records, r => r.Contains("SessionUpdate"));
    }

    [Fact]
    public async Task Session_error_and_failed_exit_are_remembered()
    {
        var status = new CopilotStatus();
        var stdout = "{\"type\":\"session.error\",\"data\":{\"message\":\"boom\"}}\n{\"type\":\"result\",\"exitCode\":1}\n";
        var records = await StreamCaptures.ParseAsync(new CopilotParser(true, status), stdout, TestContext.Current.CancellationToken);
        Assert.Empty(records);
        Assert.Equal("boom", status.PendingError);
        Assert.Equal(1, status.ResultExit);
    }

    [Fact]
    public async Task A_failed_tool_shows_its_error()
    {
        var stdout = "{\"type\":\"tool.execution_complete\",\"data\":{\"toolCallId\":\"x\",\"success\":false,\"error\":{\"message\":\"denied\"}}}\n";
        var records = await StreamCaptures.ParseAsync(new CopilotParser(), stdout, TestContext.Current.CancellationToken);
        Assert.Single(records);
        Assert.Contains("\"output\":\"denied\"", records[0]);
        Assert.Contains("\"is_error\":true", records[0]);
    }
}
