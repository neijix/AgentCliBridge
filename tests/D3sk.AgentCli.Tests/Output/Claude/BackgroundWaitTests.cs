using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Output.Claude;

/// <summary>
/// The background wait of a Claude turn, fed the recorded stdout of CLI 2.1.330 (<c>tests/fixtures/claude/2.1.330</c>):
/// run 1 lists a shell task open before its first result, run 2 takes a message and an approval during the wait.
/// </summary>
public class BackgroundWaitTests
{
    private const string TaskRun = "background-task.stdout.jsonl";
    private const string InputRun = "background-task-input.stdout.jsonl";
    private const string FirstReply = "The 12-tick loop is running in the background, and I'll let you know when it finishes.";
    private const string RaceRun = "background-task-race.stdout.jsonl";
    private const string RaceReply = "The background sleep is running. Here is the story:\n\nThe keeper lit the lamp.";
    private const string RaceFollowUp = "The background sleep finished, so the task is complete.";
    private const string EchoRun = "background-task-echo.stdout.jsonl";
    private const string EchoReply = "Both sleeps finished: the 3-second background sleep completed, and the 10-second foreground sleep returned.";
    private const string StoppedRun = "background-task-stopped.stdout.jsonl";
    private const string StoppedReply = "I started the 120-second sleep in the background and stopped it with TaskStop.";
    private const string FollowUp = "The background loop finished all 12 ticks and exited with code 0.";

    /// <summary>The parser, a live input bound to a recording writer, and what the parser did to them.</summary>
    private sealed class Rig(bool wait)
    {
        public TurnDeadline Deadline { get; } = new(TimeSpan.FromSeconds(5));
        public TurnInput Input { get; } = new();
        public List<string> Written { get; } = [];
        public int StdinClosed { get; private set; }
        public List<StreamEvent> Events { get; } = [];

        public string Text => string.Concat(Events.OfType<TextDelta>().Select(t => t.Text));

        public async Task RunAsync(IEnumerable<string> lines, Action<int>? beforeLine = null, Action<StreamEvent>? onEvent = null)
        {
            bool Write(JsonObject payload)
            {
                Written.Add(payload.ToJsonString());
                return true;
            }
            Input.Bind(Write, "the prompt");
            var parser = new ClaudeOutputParser(true, Deadline, null, new LiveLines(Input, Write), () => StdinClosed++, wait);
            await foreach (var e in parser.ParseAsync(Feed(lines, beforeLine), TestContext.Current.CancellationToken))
            {
                Events.Add(e);
                onEvent?.Invoke(e);
            }
        }
    }

    /// <summary>Each line as the runner would hand it over; <paramref name="beforeLine"/> sees the 1-based number of the line about to be read.</summary>
    private static async IAsyncEnumerable<ChildLine> Feed(IEnumerable<string> lines, Action<int>? beforeLine, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var number = 0;
        foreach (var line in lines)
        {
            number++;
            beforeLine?.Invoke(number);
            yield return new ChildLine(Encoding.UTF8.GetBytes(line + "\n"));
        }
        await Task.CompletedTask;
    }

    private static string[] Recording(string name) => File.ReadAllLines(Path.Combine(FixtureFolder(), name), Encoding.UTF8);

    private static string FixtureFolder()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "global.json")))
        {
            dir = dir.Parent;
        }
        return Path.Combine(dir?.FullName ?? throw new InvalidOperationException("repo root (global.json) not found"), "tests", "fixtures", "claude", "2.1.330");
    }

    private static bool IsTextDelta(string line) => line.Contains("\"text_delta\"", StringComparison.Ordinal);

    private static IEnumerable<string> Numbered(string name, Func<int, string, string?> keep) =>
        Recording(name).Select((line, i) => keep(i + 1, line)).OfType<string>();

    [Fact]
    public async Task A_result_with_a_task_open_starts_no_deadline_and_leaves_the_input_open()
    {
        var rig = new Rig(wait: true);
        var checkedDuringWait = false;
        await rig.RunAsync(Recording(TaskRun), before =>
        {
            if (before == 42) // the line after result #1: the shell task is still listed open
            {
                Assert.False(rig.Deadline.Started);
                Assert.True(rig.Input.IsOpen);
                Assert.Equal(0, rig.StdinClosed);
                checkedDuringWait = true;
            }
        });

        Assert.True(checkedDuringWait);
        Assert.True(rig.Deadline.Started); // result #2: nothing open any more
        Assert.False(rig.Input.IsOpen);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_the_wait_the_first_result_ends_the_turn_as_before_even_with_a_task_open()
    {
        var rig = new Rig(wait: false);
        var checkedAtResult = false;
        await rig.RunAsync(Recording(TaskRun), before =>
        {
            if (before == 42)
            {
                Assert.True(rig.Deadline.Started); // a shell task is not counted
                Assert.False(rig.Input.IsOpen);
                Assert.Equal(1, rig.StdinClosed);
                checkedAtResult = true;
            }
        });

        Assert.True(checkedAtResult);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_the_wait_a_background_agent_still_holds_the_deadline_back_and_a_shell_does_not()
    {
        var agent = new Rig(wait: false);
        await agent.RunAsync(["{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"local_agent\"}]}", "{\"type\":\"result\"}"]);
        Assert.False(agent.Deadline.Started);

        var shell = new Rig(wait: false);
        await shell.RunAsync(["{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"local_bash\"}]}", "{\"type\":\"result\"}"]);
        Assert.True(shell.Deadline.Started);
    }

    [Fact]
    public async Task A_result_with_no_task_open_ends_the_turn_even_when_the_wait_was_asked_for()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync(["{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[]}", "{\"type\":\"result\"}"]);

        Assert.True(rig.Deadline.Started);
        Assert.False(rig.Input.IsOpen);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_failed_result_with_a_task_open_keeps_the_wait_going_and_still_reports_the_error()
    {
        var rig = new Rig(wait: true);
        var checkedAfterFailure = false;
        await rig.RunAsync(
            [
                "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"local_bash\"}]}",
                "{\"type\":\"result\",\"subtype\":\"error\",\"is_error\":true,\"result\":\"Failed to authenticate\"}",
                "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[]}",
                "{\"type\":\"result\"}",
            ],
            before =>
            {
                if (before == 3) // the line after the failed result: the task is still listed open
                {
                    Assert.False(rig.Deadline.Started);
                    Assert.True(rig.Input.IsOpen);
                    Assert.Equal(0, rig.StdinClosed);
                    checkedAfterFailure = true;
                }
            });

        Assert.True(checkedAfterFailure);
        Assert.Contains(rig.Events, e => e is StreamError { Message: "Failed to authenticate" });
        Assert.True(rig.Deadline.Started); // the next result: nothing open any more
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_failed_result_with_no_task_open_ends_the_turn()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync(["{\"type\":\"result\",\"subtype\":\"error\",\"is_error\":true,\"result\":\"Failed to authenticate\"}"]);

        Assert.True(rig.Deadline.Started);
        Assert.Contains(rig.Events, e => e is StreamError);
    }

    [Fact]
    public async Task A_task_listed_after_the_result_that_started_the_deadline_does_not_stop_it()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync(
        [
            "{\"type\":\"result\"}",
            "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_type\":\"local_bash\"}]}",
        ]);

        Assert.True(rig.Deadline.Started);
        Assert.False(rig.Input.IsOpen);
    }

    [Fact]
    public async Task A_message_and_an_approval_during_the_wait_reach_the_child_and_a_result_with_the_task_open_keeps_waiting()
    {
        var rig = new Rig(wait: true);
        string? pending = null;
        var answered = false;
        var held = new List<bool>();
        await rig.RunAsync(
            Recording(InputRun),
            before =>
            {
                if (before == 50) // after result #1, the task open
                {
                    Assert.True(rig.Input.Say("ping"));
                }
                if (before == 61) // after result #2, which answered that message: the task is still open
                {
                    held.Add(!rig.Deadline.Started && rig.Input.IsOpen && rig.StdinClosed == 0);
                }
                if (before == 83 && pending is { } id) // the follow-up's approval, after the task ended
                {
                    answered = rig.Input.Answer(id, allow: true);
                }
            },
            e =>
            {
                if (e is ApprovalRequest request)
                {
                    pending = request.RequestId;
                }
            });

        Assert.Equal([true], held);
        Assert.True(answered);
        Assert.Contains(rig.Written, w => w.Contains("\"content\":\"ping\"", StringComparison.Ordinal));
        Assert.Contains(rig.Written, w => w.Contains("\"behavior\":\"allow\"", StringComparison.Ordinal));
        Assert.Contains(rig.Events, e => e is InputAccepted);
        Assert.True(rig.Deadline.Started); // result #3
        Assert.False(rig.Input.IsOpen);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task The_follow_up_reply_joins_the_turn_after_a_paragraph_break_and_the_result_texts_repeat_nothing()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync(Recording(TaskRun));

        Assert.Equal($"{FirstReply}\n\n{FollowUp}", rig.Text);
    }

    [Fact]
    public async Task Each_reply_of_the_wait_is_a_paragraph_and_the_follow_up_shows_its_tool_events()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync(Recording(InputRun));

        Assert.Equal(
            "The 12-tick counter is running in the background, and when it finishes I'll run `git init` here."
            + "\n\npong"
            + "\n\nThe counter finished and `git init` created an empty Git repository in `C:\\work\\project`.",
            rig.Text);
        var gitInit = rig.Events.FindIndex(e => e is ToolCall call && (call.Arguments?.ToJsonString() ?? "").Contains("git init", StringComparison.Ordinal));
        var pong = rig.Events.FindIndex(e => e is TextDelta { Text: "pong" });
        var closing = rig.Events.FindIndex(e => e is TextDelta text && text.Text.StartsWith("The counter finished", StringComparison.Ordinal));
        Assert.True(pong >= 0 && gitInit > pong && closing > gitInit);
        Assert.Contains(rig.Events.Skip(gitInit), e => e is ToolResult);
    }

    [Fact]
    public async Task A_follow_up_result_text_shows_when_that_reply_streamed_none()
    {
        // run 1 without the follow-up's streamed text: only its result carries the sentence
        var rig = new Rig(wait: true);
        await rig.RunAsync(Numbered(TaskRun, (number, line) => number > 41 && IsTextDelta(line) ? null : line));

        Assert.Equal($"{FirstReply}\n\n{FollowUp}", rig.Text);
    }

    [Fact]
    public async Task No_paragraph_break_comes_before_a_follow_up_when_reply_one_showed_no_text()
    {
        // run 1 without reply 1's text, streamed or in its result
        var rig = new Rig(wait: true);
        await rig.RunAsync(Numbered(TaskRun, (number, line) =>
            number < 41 && IsTextDelta(line) ? null : number == 41 ? line.Replace(FirstReply, "", StringComparison.Ordinal) : line));

        Assert.Equal(FollowUp, rig.Text);
    }

    [Fact]
    public async Task A_result_after_the_task_ended_but_before_its_notice_was_taken_keeps_waiting_for_the_follow_up()
    {
        var rig = new Rig(wait: true);
        var heldAtFollowUp = false;
        await rig.RunAsync(Recording(RaceRun), before =>
        {
            if (before == 52) // the line after result #1: the list is [] but the CLI has not yet run the task's notice
            {
                heldAtFollowUp = !rig.Deadline.Started && rig.Input.IsOpen && rig.StdinClosed == 0;
            }
        });

        Assert.True(heldAtFollowUp);
        Assert.True(rig.Deadline.Started); // result #2, the follow-up's: nothing open, no notice waiting
        Assert.False(rig.Input.IsOpen);
        Assert.Equal(1, rig.StdinClosed);
        Assert.Equal($"{RaceReply}\n\n{RaceFollowUp}", rig.Text);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_the_wait_the_result_before_the_notice_still_starts_the_deadline()
    {
        var rig = new Rig(wait: false);
        var started = false;
        await rig.RunAsync(Recording(RaceRun), before =>
        {
            if (before == 52)
            {
                started = rig.Deadline.Started;
            }
        });

        Assert.True(started);
    }

    [Fact]
    public async Task A_notice_echoed_inside_the_reply_is_taken_by_it_and_is_not_the_users_message()
    {
        // run 4: the task ended during a foreground command; the CLI echoed its notice (isReplay) before the reply's result and ran no follow-up
        var rig = new Rig(wait: true);
        await rig.RunAsync(Recording(EchoRun));

        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
        Assert.DoesNotContain(rig.Events, e => e is InputAccepted);
        Assert.Equal(EchoReply, rig.Text);
    }

    [Fact]
    public async Task A_notice_of_a_task_that_was_never_listed_open_holds_nothing_back()
    {
        // run 4's foreground command has a task_started and a completed notice, but no background_tasks_changed ever lists it:
        // with the listed task's echo and the notice before it cut, nothing is pending at the result
        var rig = new Rig(wait: true);
        await rig.RunAsync(Numbered(EchoRun, (number, line) => number is 33 or 38 ? null : line));

        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_notice_the_model_stopped_itself_comes_with_no_follow_up_so_the_next_result_ends_the_wait()
    {
        // run 5: TaskStop on the listed task; its notice says "stopped" and the CLI ran no follow-up turn
        var rig = new Rig(wait: true);
        await rig.RunAsync(Recording(StoppedRun));

        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
        Assert.Equal(StoppedReply, rig.Text);
    }

    [Fact]
    public async Task A_notice_echo_never_reaches_the_live_input_even_with_a_message_pending()
    {
        // lines hand-built from the recorded shapes (run 4's echo, run 1's task list)
        var rig = new Rig(wait: true);
        var held = false;
        await rig.RunAsync(
            [Prompt(), List(Listed("t1", "r1")), Notice("t1", "r1"), List(), NoticeEcho("r1"), Result()],
            before =>
            {
                if (before == 2)
                {
                    Assert.True(rig.Input.Say("ping")); // on its way when the echo and the result arrive
                }
                if (before == 6) // the result, after the echo
                {
                    held = rig.Input.IsOpen && rig.StdinClosed == 0 && !rig.Events.Any(e => e is InputAccepted);
                }
            });

        Assert.True(held);
        Assert.False(rig.Deadline.Started); // the message is still unread: the turn goes on
        Assert.True(rig.Input.IsOpen);
        Assert.Equal(0, rig.StdinClosed);
    }

    [Fact]
    public async Task Two_tasks_ending_together_keep_the_wait_until_each_ones_follow_up_has_its_result()
    {
        // hand-built from the recorded shapes: each follow-up result names its task by origin.runId
        var rig = new Rig(wait: true);
        var held = new Dictionary<int, bool>();
        await rig.RunAsync(
            [
                Prompt(), List(Listed("a", "ra"), Listed("b", "rb")), Result(),
                Notice("a", "ra"), Notice("b", "rb"), List(),
                Init(), Result("rb"),
                Init(), Result("ra"),
            ],
            before =>
            {
                if (before is 4 or 9) // after the first reply's result, after the first follow-up's
                {
                    held[before] = !rig.Deadline.Started && rig.Input.IsOpen && rig.StdinClosed == 0;
                }
            });

        Assert.Equal(new Dictionary<int, bool> { [4] = true, [9] = true }, held);
        Assert.True(rig.Deadline.Started); // task a's follow-up result, the last one
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_follow_up_result_naming_a_run_that_is_not_pending_takes_no_other_notice()
    {
        var rig = new Rig(wait: true);
        var held = new Dictionary<int, bool>();
        await rig.RunAsync(
            [
                Prompt(), List(Listed("a", "ra"), Listed("b", "rb")), Result(),
                Notice("a", "ra"), Notice("b", "rb"), List(),
                Init(), Result("rb"),
                Init(), Result("rb"), // rb again: nothing of that run is pending, ra's notice stays
                Init(), Result("ra"),
            ],
            before =>
            {
                if (before is 9 or 11)
                {
                    held[before] = !rig.Deadline.Started && rig.Input.IsOpen && rig.StdinClosed == 0;
                }
            });

        Assert.Equal(new Dictionary<int, bool> { [9] = true, [11] = true }, held);
        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_notice_repeated_for_the_same_task_counts_once()
    {
        var rig = new Rig(wait: true);
        await rig.RunAsync([Prompt(), List(Listed("a", "ra")), Result(), Notice("a", "ra"), Notice("a", "ra"), List(), Init(), Result("ra")]);

        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_message_turn_in_the_middle_of_a_pending_notice_does_not_take_it()
    {
        // the user's message gets its own init and result while task a's notice still waits for its follow-up
        var rig = new Rig(wait: true);
        var held = false;
        await rig.RunAsync(
            [
                Prompt(), List(Listed("a", "ra")), Result(),
                Notice("a", "ra"), List(),
                Init(), Result(), // the message turn: no origin
                Init(), Result("ra"),
            ],
            before =>
            {
                if (before == 8)
                {
                    held = !rig.Deadline.Started && rig.Input.IsOpen && rig.StdinClosed == 0;
                }
            });

        Assert.True(held);
        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    public async Task A_follow_up_result_that_names_no_task_takes_the_oldest_notice()
    {
        var rig = new Rig(wait: true);
        var held = false;
        await rig.RunAsync(
            [
                Prompt(), List(Listed("a", "ra"), Listed("b", "rb")), Result(),
                Notice("a", "ra"), Notice("b", "rb"), List(),
                Init(), Result(""),
                Init(), Result(""),
            ],
            before =>
            {
                if (before == 9)
                {
                    held = !rig.Deadline.Started;
                }
            });

        Assert.True(held);
        Assert.True(rig.Deadline.Started);
    }

    [Fact]
    public async Task A_notice_comes_after_the_first_result_and_the_follow_ups_result_takes_it()
    {
        // run 1 as recorded: the notice follows result #1, the follow-up's result carries origin.runId
        var rig = new Rig(wait: true);
        await rig.RunAsync(Recording(TaskRun));

        Assert.True(rig.Deadline.Started);
        Assert.Equal(1, rig.StdinClosed);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_the_wait_a_notice_echo_is_read_as_before()
    {
        // 0.7.0 has no notice rule: the echo is an ordinary replayed user line
        var rig = new Rig(wait: false);
        await rig.RunAsync([Prompt(), NoticeEcho("r1")]);

        Assert.Contains(rig.Events, e => e is InputAccepted);
    }

    private static string Prompt() => "{\"type\":\"user\",\"isReplay\":true,\"message\":{\"role\":\"user\",\"content\":\"the prompt\"}}";

    private static string Listed(string id, string run) => $"{{\"task_id\":\"{id}\",\"run_id\":\"{run}\",\"task_type\":\"local_bash\"}}";

    private static string List(params string[] tasks) => $"{{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{string.Join(',', tasks)}]}}";

    private static string Notice(string id, string run, string status = "completed") =>
        $"{{\"type\":\"system\",\"subtype\":\"task_notification\",\"task_id\":\"{id}\",\"run_id\":\"{run}\",\"status\":\"{status}\"}}";

    private static string NoticeEcho(string run) =>
        $"{{\"type\":\"user\",\"isReplay\":true,\"message\":{{\"role\":\"user\",\"content\":\"<task-notification/>\"}},\"origin\":{{\"kind\":\"task-notification\",\"runId\":\"{run}\"}}}}";

    private static string Init() => "{\"type\":\"system\",\"subtype\":\"init\"}";

    /// <summary>A <c>result</c>: a follow-up's when <paramref name="run"/> is not null (an empty one names no task), else a plain reply's.</summary>
    private static string Result(string? run = null) =>
        run is null ? "{\"type\":\"result\"}"
        : run.Length == 0 ? "{\"type\":\"result\",\"origin\":{\"kind\":\"task-notification\"}}"
        : $"{{\"type\":\"result\",\"origin\":{{\"kind\":\"task-notification\",\"runId\":\"{run}\"}}}}";

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Without_the_wait_the_replies_of_the_recording_get_no_break_between_them()
    {
        var rig = new Rig(wait: false);
        await rig.RunAsync(Recording(TaskRun));

        Assert.Equal(FirstReply + FollowUp, rig.Text);
    }
}
