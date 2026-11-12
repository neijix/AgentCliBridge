using System.Text;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Output.Common;

public class CommonTests
{
    private static async IAsyncEnumerable<ChildLine> Lines(params string[] texts)
    {
        foreach (var t in texts)
        {
            yield return new ChildLine(Encoding.UTF8.GetBytes(t));
        }

        await Task.CompletedTask;
    }

    [Fact]
    public async Task Json_lines_skip_blanks_and_flag_what_is_not_json()
    {
        var all = new List<JsonLine>();
        await foreach (var l in JsonLine.ReadAsync(Lines("{\"a\":1}\n", "  \n", "\n", "not json\n", "null\n", "[1]")))
        {
            all.Add(l);
        }

        Assert.Equal(4, all.Count);
        Assert.True(all[0].Parsed);
        Assert.Equal(1, (int)all[0].AsObject()["a"]!);
        Assert.False(all[1].Parsed);
        Assert.Equal("not json", all[1].Text);
        Assert.True(all[2].Parsed);
        Assert.Null(all[2].Value);
        Assert.True(all[3].Parsed);
        Assert.Empty(all[3].AsObject());
    }

    [Fact]
    public void An_invalid_utf8_line_is_replaced_not_thrown()
    {
        var line = JsonLine.Parse(new ChildLine([0x7b, 0xff, 0x7d]).Text.Trim());
        Assert.False(line.Parsed);
    }

    [Fact]
    public void As_object_is_empty_for_other_json()
    {
        Assert.Empty(Json.AsObject(null));
        Assert.Empty(Json.AsObject(JsonNode.Parse("\"x\"")));
        Assert.Single(Json.AsObject(JsonNode.Parse("{\"k\":1}")));
    }

    [Fact]
    public void Raw_text_is_empty_when_the_parser_kept_it_all()
    {
        Assert.Equal("", Json.RawText(null, ""));
        Assert.Equal("", Json.RawText(JsonNode.Parse("\"abc\""), "abc"));
        Assert.Equal("abcdef", Json.RawText(JsonNode.Parse("\"abcdef\""), "abc"));
        Assert.Equal("{\"t\": \"é\"}", Json.RawText(JsonNode.Parse("{\"t\":\"é\"}"), "x"));
        Assert.Equal("[1, 2]", Json.RawText(JsonNode.Parse("[1,2]"), "x"));
        Assert.Equal("", Json.RawText(JsonNode.Parse("[1]"), "[1]"));
    }

    [Fact]
    public void A_session_id_is_emitted_once()
    {
        var ids = new SessionIds();
        Assert.Equal(new SessionUpdate("s1"), ids.Dedupe("s1"));
        Assert.Null(ids.Dedupe("s1"));
        Assert.Null(ids.Dedupe(""));
        Assert.Null(ids.Dedupe(null));
        Assert.Null(ids.Dedupe(JsonNode.Parse("0")));
        Assert.Equal(new SessionUpdate("s2"), ids.Dedupe("s2"));
        Assert.Equal(new SessionUpdate("s1"), ids.Dedupe("s1"));
    }

    [Fact]
    public void Only_opencode_insists_on_a_string_id()
    {
        Assert.Null(new SessionIds().Dedupe(JsonNode.Parse("42"), requireString: true));
        Assert.Equal(new SessionUpdate("42"), new SessionIds().Dedupe(JsonNode.Parse("42")));
        Assert.Equal(new SessionUpdate("x"), new SessionIds().Dedupe("x", requireString: true));
    }

    private sealed class EchoParser : IOutputParser
    {
        public async IAsyncEnumerable<StreamEvent> ParseAsync(IAsyncEnumerable<ChildLine> lines,
            [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
        {
            var ids = new SessionIds();
            await foreach (var line in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
            {
                var o = line.AsObject();
                if (ids.Dedupe(o["session"]) is { } update)
                {
                    yield return update;
                }

                if (Json.AsString(o["text"]) is { } text)
                {
                    yield return new TextDelta(text);
                }
            }
        }
    }

    [Fact]
    public async Task A_parser_turns_lines_into_events_with_state_per_call()
    {
        IOutputParser parser = new EchoParser();
        for (var run = 0; run < 2; run++)
        {
            var events = new List<StreamEvent>();
            await foreach (var e in parser.ParseAsync(Lines("{\"session\":\"s\",\"text\":\"a\"}\n", "junk\n", "{\"session\":\"s\",\"text\":\"b\"}\n"),
                TestContext.Current.CancellationToken))
            {
                events.Add(e);
            }

            Assert.Equal([new SessionUpdate("s"), new TextDelta("a"), new TextDelta("b")], events);
        }
    }
}
