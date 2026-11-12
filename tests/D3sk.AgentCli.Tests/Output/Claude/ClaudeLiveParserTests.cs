using D3sk.AgentCli.Control;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Claude;

/// <summary>The live wires of the Claude parser: control lines, a resumed session's empty result, the turn's end.</summary>
public class ClaudeLiveParserTests
{
    private const string Prompt = "{\"type\":\"user\",\"isReplay\":true,\"message\":{\"role\":\"user\",\"content\":\"hi\"}}";
    private const string More = "{\"type\":\"user\",\"isReplay\":true,\"message\":{\"role\":\"user\",\"content\":\"more\"}}";
    private const string Text = "{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"pong\"}}}";
    private const string EmptyResume = "{\"type\":\"result\",\"subtype\":\"success\",\"session_id\":\"old\",\"result\":\"\",\"num_turns\":0}";
    private const string Done = "{\"type\":\"result\",\"subtype\":\"success\",\"session_id\":\"s1\",\"result\":\"pong\",\"num_turns\":1}";

    private static (ClaudeOutputParser Parser, TurnInput Input, TurnDeadline Deadline, int[] Closed) Rig()
    {
        var input = new TurnInput();
        input.Bind(_ => true, "hi");
        var deadline = new TurnDeadline(TimeSpan.FromSeconds(30));
        var closed = new int[1];
        var live = new LiveLines(input, _ => true);
        return (new ClaudeOutputParser(true, deadline, null, live, () => closed[0]++), input, deadline, closed);
    }

    private static Task<List<string>> Parse(ClaudeOutputParser parser, params string[] lines) =>
        StreamCaptures.ParseAsync(parser, string.Join('\n', lines) + "\n", TestContext.Current.CancellationToken);

    [Fact]
    [Trait("Preserve", "P14")]
    public async Task A_resumed_sessions_empty_result_does_not_end_the_turn()
    {
        var (parser, input, deadline, closed) = Rig();

        var records = await Parse(parser, EmptyResume, Prompt, Text);

        Assert.DoesNotContain(records, r => r.Contains("StreamError", StringComparison.Ordinal));
        Assert.False(deadline.Started);
        Assert.Equal(0, closed[0]);
        Assert.True(input.IsOpen);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public async Task The_real_result_closes_stdin_and_starts_the_deadline()
    {
        var (parser, input, deadline, closed) = Rig();

        var records = await Parse(parser, EmptyResume, Prompt, Text, Done);

        Assert.Contains("{\"event\":\"TextDelta\",\"text\":\"pong\"}", records);
        Assert.True(deadline.Started);
        Assert.Equal(1, closed[0]);
        Assert.False(input.IsOpen);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public async Task A_message_still_on_its_way_keeps_stdin_open_until_the_result_that_answers_it()
    {
        var (parser, input, deadline, closed) = Rig();
        Assert.True(input.Say("more"));

        var first = await Parse(parser, Prompt, Text, Done);

        Assert.False(deadline.Started);
        Assert.Equal(0, closed[0]);
        Assert.True(input.IsOpen);
        Assert.Contains(first, r => r.Contains("TextDelta", StringComparison.Ordinal));

        var second = await Parse(parser, More, Done);

        Assert.Contains(second, r => r.Contains("InputAccepted", StringComparison.Ordinal) && r.Contains("more", StringComparison.Ordinal));
        Assert.True(deadline.Started);
        Assert.Equal(1, closed[0]);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public async Task A_control_request_becomes_an_approval_only_on_a_live_turn()
    {
        var ask = "{\"type\":\"control_request\",\"request_id\":\"r1\",\"request\":{\"subtype\":\"can_use_tool\",\"tool_name\":\"Edit\",\"tool_use_id\":\"u1\",\"input\":{}}}";
        var (parser, _, _, _) = Rig();

        Assert.Contains(await Parse(parser, ask), r => r.Contains("ApprovalRequest", StringComparison.Ordinal));
        Assert.Empty(await Parse(new ClaudeOutputParser(), ask));
    }
}
