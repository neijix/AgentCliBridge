using D3sk.AgentCli.Output.Grok;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Output.Grok;

public class GrokOutputParserTests
{
    private static readonly string[] WrongFields = ["{\"type\": \"stream_event\", \"event\": \"x\"}", "{\"type\": \"user\", \"message\": []}"];

    [Theory]
    [Trait("Category", "Preserve")]
    [InlineData("grok__cancelled_by_itself")]
    [InlineData("grok__tool_output_unwrapped")]
    public Task A_recorded_turn_yields_its_expected_events(string name) =>
        StreamCaptures.AssertReplaysAsync(new GrokOutputParser(), name, TestContext.Current.CancellationToken);

    [Theory]
    [Trait("Category", "Preserve")]
    [InlineData("grok__cancelled_by_itself")]
    [InlineData("grok__tool_output_unwrapped")]
    public Task A_line_that_is_not_the_expected_object_changes_nothing(string name) =>
        StreamCaptures.AssertJunkChangesNothingAsync(new GrokOutputParser(), name,
            StreamCaptures.NotObjects.Concat(WrongFields), TestContext.Current.CancellationToken);
}
