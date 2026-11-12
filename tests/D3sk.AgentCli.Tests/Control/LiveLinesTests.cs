using System.Text;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Control;

/// <summary>The control lines of a live turn, alone and against a fake Claude Code child.</summary>
public class LiveLinesTests
{
    private static (TurnInput Input, LiveLines Lines, List<JsonObject> Written) Live()
    {
        var written = new List<JsonObject>();
        bool Write(JsonObject payload)
        {
            written.Add((JsonObject)payload.DeepClone());
            return true;
        }

        var input = new TurnInput();
        input.Bind(Write, "hi");
        written.Clear();
        return (input, new LiveLines(input, Write), written);
    }

    private static List<StreamEvent> Feed(LiveLines lines, string json)
    {
        Assert.True(lines.TryHandle((JsonObject)JsonNode.Parse(json)!, out var events));
        return events;
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_can_use_tool_request_becomes_an_approval_request()
    {
        var (_, lines, _) = Live();
        var events = Feed(lines, """{"type":"control_request","request_id":"r1","request":{"subtype":"can_use_tool","tool_name":"Edit","input":{"file_path":"a"},"tool_use_id":"t1","description":"Edit a"}}""");

        var approval = Assert.IsType<ApprovalRequest>(Assert.Single(events));
        Assert.Equal(("r1", "t1", "Edit", "Edit a"), (approval.RequestId, approval.CallId, approval.Name, approval.Description));
        Assert.Equal("""{"file_path":"a"}""", approval.Arguments!.ToJsonString());
    }

    [Fact]
    public void A_request_without_a_tool_name_or_input_still_asks()
    {
        var (_, lines, _) = Live();
        var approval = Assert.IsType<ApprovalRequest>(Assert.Single(Feed(lines, """{"type":"control_request","request_id":"r1","request":{"subtype":"can_use_tool"}}""")));
        Assert.Equal(("tool", "", ""), (approval.Name, approval.CallId, approval.Description));
        Assert.Equal("{}", approval.Arguments!.ToJsonString());
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void An_unsupported_control_request_is_refused_instead_of_left_waiting()
    {
        var (_, lines, written) = Live();
        Assert.Empty(Feed(lines, """{"type":"control_request","request_id":"r1","request":{"subtype":"hook_callback"}}"""));

        var response = written.Single()["response"]!;
        Assert.Equal("error", (string)response["subtype"]!);
        Assert.Equal("r1", (string)response["request_id"]!);
        Assert.Equal("Unsupported control request: hook_callback", (string)response["error"]!);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void The_prompts_own_echo_is_not_a_message_but_a_later_one_is_accepted()
    {
        var (input, lines, _) = Live();
        Assert.True(input.Say("also run the tests"));

        Assert.Empty(Feed(lines, """{"type":"user","isReplay":true,"message":{"content":"hi"}}"""));
        var accepted = Feed(lines, """{"type":"user","isReplay":true,"message":{"content":[{"type":"text","text":"also run "},{"type":"image"},{"type":"text","text":"the tests"}]}}""");

        Assert.Equal(new InputAccepted("also run the tests"), Assert.Single(accepted));
        Assert.True(lines.TurnEnded());
    }

    [Fact]
    public void A_user_line_that_is_not_a_replay_and_other_lines_are_left_to_the_parser()
    {
        var (_, lines, _) = Live();
        foreach (var json in new[] { """{"type":"user","message":{"content":"x"}}""", """{"type":"assistant"}""", """{"type":"result"}""", """{"type":"user","isReplay":false}""" })
        {
            Assert.False(lines.TryHandle((JsonObject)JsonNode.Parse(json)!, out var events));
            Assert.Empty(events);
        }
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_mode_answer_becomes_mode_changed_and_only_ours_do()
    {
        var (input, lines, written) = Live();
        Assert.True(input.SetPermissionMode("auto"));
        Assert.True(input.SetPermissionMode("bypassPermissions"));
        Assert.True(input.SetPermissionMode("plan"));
        var ids = written.Select(w => (string)w["request_id"]!).ToArray();

        Assert.Equal(new ModeChanged("auto"), Assert.Single(Feed(lines, """{"type":"control_response","response":{"subtype":"success","request_id":"ID","response":{"mode":"auto"}}}""".Replace("ID", ids[0]))));
        Assert.Equal(new ModeChanged("bypassPermissions", "not launched with bypass"), Assert.Single(Feed(lines, """{"type":"control_response","response":{"subtype":"error","request_id":"ID","error":"not launched with bypass"}}""".Replace("ID", ids[1]))));
        Assert.Equal(new ModeChanged("plan", "The CLI refused the mode change."), Assert.Single(Feed(lines, """{"type":"control_response","response":{"subtype":"error","request_id":"ID"}}""".Replace("ID", ids[2]))));
        Assert.Empty(Feed(lines, """{"type":"control_response","response":{"subtype":"success","request_id":"d3sk-mode-1"}}"""));
        Assert.Empty(Feed(lines, """{"type":"control_response","response":{"subtype":"success","request_id":"someone-else"}}"""));
    }

    [Fact]
    public void A_cancelled_request_is_withdrawn()
    {
        var (input, lines, _) = Live();
        Feed(lines, """{"type":"control_request","request_id":"r1","request":{"subtype":"can_use_tool","input":{}}}""");
        Assert.Empty(Feed(lines, """{"type":"control_cancel_request","request_id":"r1"}"""));
        Assert.False(input.Answer("r1", true));
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void Only_the_exact_stale_result_shape_is_an_empty_resume()
    {
        var (_, lines, _) = Live();
        var stale = (JsonObject)JsonNode.Parse("""{"type":"result","subtype":"success","result":"","num_turns":0}""")!;
        Assert.True(lines.IsEmptyResume(stale, isFailure: false));
        Assert.False(lines.IsEmptyResume(stale, isFailure: true));
        Assert.False(lines.IsEmptyResume((JsonObject)JsonNode.Parse("""{"result":"","num_turns":2}""")!, false));
        Assert.False(lines.IsEmptyResume((JsonObject)JsonNode.Parse("""{"result":"text","num_turns":0}""")!, false));
        Assert.False(lines.IsEmptyResume((JsonObject)JsonNode.Parse("""{"result":""}""")!, false));

        Feed(lines, """{"type":"user","isReplay":true,"message":{"content":"hi"}}""");
        Assert.False(lines.IsEmptyResume(stale, isFailure: false)); // the prompt was taken: this is a real result
    }

    private const string FakeClaude = """
        echo '{"type":"system","subtype":"init","session_id":"s1"}'
        read prompt; echo "$prompt" >> "$FAKE_LOG"
        echo '{"type":"user","isReplay":true,"message":{"content":"hi"}}'
        echo '{"type":"control_request","request_id":"r1","request":{"subtype":"can_use_tool","tool_name":"Edit","input":{"file_path":"a"},"tool_use_id":"t1","description":"Edit a"}}'
        read answer; echo "$answer" >> "$FAKE_LOG"
        read said; echo "$said" >> "$FAKE_LOG"
        echo '{"type":"user","isReplay":true,"message":{"content":"also run the tests"}}'
        echo '{"type":"result","subtype":"success","result":"ok","session_id":"s1"}'
        """;

    [Fact]
    [Trait("Preserve", "P14")]
    public async Task A_fake_claude_is_answered_over_its_real_stdin()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "the fake child is a POSIX shell script");
        var ct = TestContext.Current.CancellationToken;
        var log = Path.Combine(Path.GetTempPath(), $"d3sk-live-{Guid.NewGuid():N}.jsonl");
        try
        {
            var live = new ChildInput();
            var input = new TurnInput();
            var lines = new LiveLines(input, p => live.WriteLine(p.ToJsonString()));
            var command = new ChildCommand
            {
                FileName = "/bin/sh",
                Arguments = ["-c", FakeClaude],
                Environment = new Dictionary<string, string> { ["PATH"] = "/usr/bin:/bin", ["FAKE_LOG"] = log },
                LiveInput = live,
            };

            var events = new List<StreamEvent>();
            var started = false;
            await foreach (var childEvent in ChildTurn.RunAsync(command, new ChildRunOptions { ExitPoll = TimeSpan.FromMilliseconds(50) }, ct))
            {
                if (childEvent is not ChildLine line)
                {
                    continue;
                }
                if (!started)
                {
                    started = true; // the child runs: its stdin is bound
                    Assert.True(input.Start(live, "hi"));
                }
                if (JsonNode.Parse(line.Bytes) is not JsonObject json || !lines.TryHandle(json, out var pieces))
                {
                    continue;
                }
                events.AddRange(pieces);
                if (pieces.OfType<ApprovalRequest>().FirstOrDefault() is { } ask)
                {
                    Assert.True(input.Answer(ask.RequestId, true));
                    Assert.True(input.Say("also run the tests"));
                }
            }

            Assert.Equal([typeof(ApprovalRequest), typeof(InputAccepted)], events.Select(e => e.GetType()).ToArray());
            Assert.Equal(new InputAccepted("also run the tests"), events[1]);
            var written = (await File.ReadAllLinesAsync(log, Encoding.UTF8, ct)).Select(l => (JsonObject)JsonNode.Parse(l)!).ToArray();
            Assert.Equal("hi", (string)written[0]["message"]!["content"]!);
            Assert.Equal("allow", (string)written[1]["response"]!["response"]!["behavior"]!);
            Assert.Equal("also run the tests", (string)written[2]["message"]!["content"]!);
        }
        finally
        {
            File.Delete(log);
        }
    }
}
