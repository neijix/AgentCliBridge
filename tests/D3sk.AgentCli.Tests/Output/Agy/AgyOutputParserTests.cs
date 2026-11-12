using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Agy;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Agy;

public class AgyOutputParserTests
{
    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    private static async Task<List<string>> Run(string stdout, bool activity = true) =>
        await StreamCaptures.ParseAsync(new AgyOutputParser { Activity = activity }, stdout, Ct);

    [Fact]
    public async Task Tool_steps_capture_replays()
    {
        await StreamCaptures.AssertReplaysAsync(new AgyOutputParser(), "agy__tool_steps", Ct);
    }

    [Fact]
    public async Task Wrong_field_types_change_nothing()
    {
        string[] wrong = ["{\"event\": \"step_update\", \"step_update\": \"x\"}", "{\"event\": \"step_update\", \"step_update\": []}"];
        await StreamCaptures.AssertJunkChangesNothingAsync(new AgyOutputParser(), "agy__tool_steps", wrong, Ct);
    }

    [Fact]
    public async Task A_line_that_is_not_an_object_is_shown_as_text()
    {
        var events = await Run("hello\nnull\n42\n[1]\n");
        Assert.Equal(
            ["{\"event\":\"TextDelta\",\"text\":\"hello\\n\"}", "{\"event\":\"TextDelta\",\"text\":\"null\\n\"}",
             "{\"event\":\"TextDelta\",\"text\":\"42\\n\"}", "{\"event\":\"TextDelta\",\"text\":\"[1]\\n\"}"], events);
    }

    [Fact]
    public async Task Activity_off_drops_tool_steps_but_keeps_text_and_the_session()
    {
        var all = await Run(StreamCaptures.Capture("agy__tool_steps"), activity: false);
        Assert.Equal(2, all.Count);
        Assert.Contains("SessionUpdate", all[0]);
        Assert.Contains("Done.", all[1]);
    }

    [Fact]
    public async Task A_failed_tool_ends_as_an_error_once()
    {
        const string step = "{\"event\":\"step_update\",\"step_update\":{\"step_index\":7,\"step_type\":\"tool\",\"tool_name\":\"run\",\"state\":\"ERROR\"}}\n";
        var events = await Run(step + step);
        Assert.Equal(
            ["{\"event\":\"ToolCall\",\"call_id\":\"7\",\"name\":\"run\",\"arguments\":{}}",
             "{\"event\":\"ToolResult\",\"call_id\":\"7\",\"output\":\"\",\"is_error\":true}"], events);
    }

    [Fact]
    public async Task The_conversation_id_is_emitted_once_across_init_and_result()
    {
        var events = await Run("{\"event\":\"init\",\"conversation_id\":\"c\"}\n{\"event\":\"result\",\"result\":{\"conversation_id\":\"c\"}}\n{\"event\":\"result\",\"result\":{\"conversation_id\":\"d\"}}\n");
        Assert.Equal(["{\"event\":\"SessionUpdate\",\"session_id\":\"c\"}", "{\"event\":\"SessionUpdate\",\"session_id\":\"d\"}"], events);
    }

    [Fact]
    public async Task Unknown_events_and_empty_deltas_yield_nothing()
    {
        var events = await Run("{\"event\":\"other\"}\n{\"event\":\"step_update\",\"step_update\":{\"step_type\":\"agent_response\",\"text_delta\":\"\"}}\n{\"x\":1}\n");
        Assert.Empty(events);
    }
}
