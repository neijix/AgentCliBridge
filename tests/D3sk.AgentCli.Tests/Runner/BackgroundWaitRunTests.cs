using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Host;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Runner;

/// <summary>
/// The background wait through the runner, against a fake CLI that replays what CLI 2.1.330 wrote around a background
/// task (see <c>tests/fixtures/claude/2.1.330</c>). The fake is a shell script on Linux and macOS and a batch file on
/// Windows, so these tests run on all three; only the two that go through <see cref="AgentTurn"/> need a POSIX CLI.
/// </summary>
public sealed class BackgroundWaitRunTests : IDisposable
{
    private const string Open = "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[{\"task_id\":\"t1\",\"task_type\":\"local_bash\"}]}";
    private static readonly TimeSpan Grace = TimeSpan.FromSeconds(1);
    private const string None = "{\"type\":\"system\",\"subtype\":\"background_tasks_changed\",\"tasks\":[]}";

    private readonly string _folder = Directory.CreateTempSubdirectory("d3sk-wait-").FullName;

    public void Dispose()
    {
        // a killed fake CLI's last process may hold its working folder for a moment (Windows)
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                Directory.Delete(_folder, true);
                return;
            }
            catch (IOException) when (attempt < 60)
            {
                Thread.Sleep(100);
            }
        }
    }

    private static string Prompt(string text) => $"{{\"type\":\"user\",\"isReplay\":true,\"message\":{{\"role\":\"user\",\"content\":\"{text}\"}}}}";

    private static string Text(string text) =>
        $"{{\"type\":\"stream_event\",\"event\":{{\"type\":\"content_block_delta\",\"index\":0,\"delta\":{{\"type\":\"text_delta\",\"text\":\"{text}\"}}}}}}";

    private static string Result(string text) => $"{{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"{text}\"}}";

    /// <summary>The fake CLI, one step at a time: read a line of stdin, print lines, sleep, wait for stdin to end.</summary>
    private sealed class FakeCli(string folder)
    {
        private readonly List<string> _script = [];
        private int _chunks;

        /// <summary>Reads one line of stdin (the prompt, then a message the host said).</summary>
        public FakeCli Read()
        {
            _script.Add(OperatingSystem.IsWindows() ? "set /p L=" : "read L");
            return this;
        }

        public FakeCli Print(params string[] lines)
        {
            var name = $"chunk{++_chunks}.txt";
            File.WriteAllText(Path.Combine(folder, name), string.Join('\n', lines) + "\n", new UTF8Encoding(false));
            _script.Add(OperatingSystem.IsWindows() ? $"type {name}" : $"cat {name}");
            return this;
        }

        public FakeCli Sleep(int seconds)
        {
            _script.Add(OperatingSystem.IsWindows() ? $"ping -n {seconds + 1} 127.0.0.1 >nul" : $"sleep {seconds}");
            return this;
        }

        /// <summary>A step written once per OS, for what the other steps cannot say.</summary>
        public FakeCli Raw(string posix, string windows)
        {
            _script.Add(OperatingSystem.IsWindows() ? windows : posix);
            return this;
        }

        /// <summary>Appends a line to <c>beat.txt</c> every second for <paramref name="seconds"/>: a live child shows by the file growing.</summary>
        public FakeCli Beat(int seconds) => Raw(
            $"i=0; while [ $i -lt {seconds} ]; do echo x >> beat.txt; sleep 1; i=$((i+1)); done",
            $"for /l %%i in (1,1,{seconds}) do (echo x>>beat.txt & ping -n 2 127.0.0.1 >nul)");

        /// <summary>Like the CLI after its last result: runs until its stdin closes.</summary>
        public FakeCli UntilStdinEnds()
        {
            _script.Add(OperatingSystem.IsWindows() ? "more >nul" : "cat >/dev/null");
            return this;
        }

        public ChildCommand Command(ChildInput live)
        {
            if (OperatingSystem.IsWindows())
            {
                File.WriteAllText(Path.Combine(folder, "fake.cmd"), "@echo off\r\n" + string.Join("\r\n", _script) + "\r\n");
                var system = Environment.GetEnvironmentVariable("SystemRoot") ?? @"C:\Windows";
                return new ChildCommand
                {
                    FileName = Environment.GetEnvironmentVariable("ComSpec") ?? Path.Combine(system, "System32", "cmd.exe"),
                    Arguments = ["/d", "/c", "fake.cmd"],
                    WorkingDirectory = folder,
                    Environment = new Dictionary<string, string> { ["SystemRoot"] = system, ["PATH"] = Path.Combine(system, "System32") },
                    LiveInput = live,
                };
            }
            File.WriteAllText(Path.Combine(folder, "fake.sh"), string.Join('\n', _script) + "\n");
            return new ChildCommand
            {
                FileName = "/bin/sh",
                Arguments = ["fake.sh"],
                WorkingDirectory = folder,
                Environment = new Dictionary<string, string> { ["PATH"] = "/usr/bin:/bin" },
                LiveInput = live,
            };
        }
    }

    /// <summary>What a run did: the events its parser yielded, how the child ended, the host's input.</summary>
    private sealed record Outcome(List<StreamEvent> Events, ChildExited? Exited, TurnInput Input, TurnDeadline Deadline)
    {
        public string Text => string.Concat(Events.OfType<TextDelta>().Select(t => t.Text));
    }

    /// <summary>The runner and the Claude parser wired as <see cref="AgentTurn"/> wires them, around the fake CLI.</summary>
    private async Task<Outcome> RunAsync(FakeCli cli, bool wait, Action<StreamEvent, TurnInput, CancellationTokenSource>? onEvent = null)
    {
        var input = new TurnInput();
        var live = LiveTurn.For(input, "claude")!;
        var deadline = new TurnDeadline(Grace);
        var options = new ChildRunOptions
        {
            Deadline = deadline,
            ExitGrace = TimeSpan.FromMilliseconds(300),
            ExitPoll = TimeSpan.FromMilliseconds(50),
            WaitForBackgroundTasks = wait,
        };
        var parser = AgentParsers.For("claude", true, deadline, null, live, options.WaitForBackgroundTasks);
        var events = new List<StreamEvent>();
        var outcome = new Outcome(events, null, input, deadline);
        ChildExited? exited = null;
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);
        try
        {
            live.Start("hi");
            async IAsyncEnumerable<ChildLine> Lines([EnumeratorCancellation] CancellationToken ct = default)
            {
                await foreach (var e in ChildTurn.RunAsync(cli.Command(live.Stdin), options, cts.Token).WithCancellation(ct))
                {
                    if (e is ChildLine line)
                    {
                        yield return line;
                    }
                    else if (e is ChildExited done)
                    {
                        exited = done;
                    }
                }
            }
            await foreach (var e in parser.ParseAsync(Lines(), cts.Token))
            {
                events.Add(e);
                onEvent?.Invoke(e, input, cts);
            }
        }
        finally
        {
            live.Dispose(); // as AgentTurn does: stdin and the host's input close with the turn
        }
        return outcome with { Exited = exited };
    }

    [Fact]
    public async Task A_message_said_during_the_wait_reaches_the_child_and_the_follow_up_ends_the_same_turn()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Read().Print(Prompt("more"), Text("pong"), Result("pong")) // answers the message, the task still open
            .Sleep(3).Print(None, Text("later"), Result("later"))
            .UntilStdinEnds();
        var said = false;

        var run = await RunAsync(cli, wait: true, (e, input, _) =>
        {
            if (e is TextDelta { Text: "first" })
            {
                said = input.Say("more");
            }
        });

        Assert.True(said);
        Assert.Contains(run.Events, e => e is InputAccepted { Text: "more" });
        Assert.Equal("first\n\npong\n\nlater", run.Text);
        Assert.Equal(0, run.Exited?.ExitCode);
        Assert.False(run.Exited!.StdoutAbandoned);
        Assert.False(run.Input.IsOpen);
        Assert.False(run.Input.Say("too late"));
    }

    [Fact]
    public async Task Without_the_wait_the_result_starts_the_deadline_and_the_child_is_stopped_as_before()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Sleep(4).Print(None, Text("later"), Result("later"));

        var clock = Stopwatch.StartNew();
        var run = await RunAsync(cli, wait: false);

        Assert.Equal("first", run.Text);
        Assert.True(run.Deadline.Expired);
        Assert.True(run.Exited!.StdoutAbandoned);
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(3), $"took {clock.Elapsed}");
    }

    [Fact]
    public async Task Asked_for_the_wait_goes_on_past_the_grace_until_the_result_with_no_task_open()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Sleep(3).Print(None, Text("later"), Result("later"))
            .UntilStdinEnds();

        var run = await RunAsync(cli, wait: true);

        Assert.Equal("first\n\nlater", run.Text);
        Assert.False(run.Deadline.Expired);
        Assert.Equal(new ChildExited(0, "", false), run.Exited);
    }

    [Fact]
    public async Task Stop_during_the_wait_kills_the_child_and_throws()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Beat(30).Print(None, Text("never"), Result("never"));
        var clock = Stopwatch.StartNew();

        var run = async () => await RunAsync(cli, wait: true, (e, _, cts) =>
        {
            if (e is TextDelta { Text: "first" })
            {
                cts.CancelAfter(TimeSpan.FromMilliseconds(2500)); // well past the 1 s grace: the wait is on, the child beating
            }
        });

        await Assert.ThrowsAnyAsync<OperationCanceledException>(run);
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(20), $"took {clock.Elapsed}");
        var beat = Path.Combine(_folder, "beat.txt");
        Assert.True(File.Exists(beat), "the fake CLI never ran");
        await Task.Delay(500, TestContext.Current.CancellationToken); // the kill has settled
        var size = new FileInfo(beat).Length;
        await Task.Delay(2500, TestContext.Current.CancellationToken);
        Assert.Equal(size, new FileInfo(beat).Length); // nothing writes any more: the child is gone
    }

    [Fact]
    public async Task A_CLI_that_exits_mid_wait_with_no_final_result_ends_the_turn_and_closes_the_input()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"));
        var clock = Stopwatch.StartNew();

        var run = await RunAsync(cli, wait: true);

        Assert.Equal("first", run.Text);
        Assert.Equal(0, run.Exited?.ExitCode);
        Assert.False(run.Input.IsOpen);
        Assert.False(run.Input.Say("too late"));
        Assert.True(clock.Elapsed < Grace + TimeSpan.FromSeconds(2), $"took {clock.Elapsed}");
    }

    [Fact]
    public async Task A_CLI_that_exits_mid_wait_while_a_task_still_holds_its_stdout_ends_within_the_grace()
    {
        var cli = new FakeCli(_folder)
            .Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Raw("sleep 4 &", "start /b ping -n 5 127.0.0.1"); // the task outlives the CLI and keeps the pipe open (its output is no JSON: skipped)
        var clock = Stopwatch.StartNew();

        var run = await RunAsync(cli, wait: true);

        Assert.Equal("first", run.Text);
        Assert.False(run.Input.IsOpen);
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(3.5), $"took {clock.Elapsed}"); // not the task's 4 s
    }

    private static AgentTurnRequest Request(string command, string binary, bool wait) => new()
    {
        Command = command,
        Prompt = "hi",
        Env = new Dictionary<string, string> { ["PATH"] = OperatingSystem.IsWindows() ? @"C:\Windows\System32" : "/usr/bin:/bin" },
        Binary = binary,
        Activity = true,
        NoGuard = true,
        NoWebScout = true,
        NoSecurityLog = true,
        Run = new ChildRunOptions { WaitForBackgroundTasks = wait, ExitGrace = TimeSpan.FromMilliseconds(300), ExitPoll = TimeSpan.FromMilliseconds(50) },
    };

    [Theory]
    [InlineData("claude", true, true)]
    [InlineData("claude", false, false)]
    [InlineData("mytool", true, true)] // an unknown command runs as a claude-flavored one
    [InlineData("grok", true, false)]
    public void Only_a_claude_flavored_turn_takes_the_wait_option(string command, bool asked, bool applied)
    {
        var launch = AgentLaunch.Prepare(Request(command, "fake-cli", asked));

        var parser = Assert.IsType<ClaudeOutputParser>(launch.Parser);
        Assert.Equal(applied, parser.BackgroundWait);
    }

    [Theory]
    [InlineData("agent")]
    [InlineData("gemini")]
    [InlineData("copilot")]
    public void Another_flavor_gets_its_own_parser_whatever_the_option_says(string command)
    {
        var launch = AgentLaunch.Prepare(Request(command, "fake-cli", wait: true));

        Assert.IsNotType<ClaudeOutputParser>(launch.Parser);
    }

    private string PosixCli(string body)
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "the fake CLI is a POSIX shell script");
        var path = Path.Combine(_folder, "cli.sh");
        File.WriteAllText(path, "#!/bin/sh\n" + body + "\n");
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        return path;
    }

    private static async Task<List<StreamEvent>> Collect(AgentTurnRequest request)
    {
        var events = new List<StreamEvent>();
        await foreach (var e in AgentTurn.RunAsync(request, TestContext.Current.CancellationToken))
        {
            events.Add(e);
        }
        return events;
    }

    [Fact]
    public async Task A_host_turn_with_the_option_gets_the_follow_up_as_events_of_the_same_turn_before_Completed()
    {
        var fake = new FakeCli(_folder).Read().Print(Prompt("hi"), Open, Text("first"), Result("first"))
            .Sleep(1).Print(None, Text("later"), Result("later")).UntilStdinEnds();
        _ = fake.Command(new ChildInput()); // writes the chunk files and the script
        var cli = PosixCli($"cd '{_folder}'\n. ./fake.sh");
        var input = new TurnInput();

        var events = await Collect(Request("claude", cli, wait: true) with { Input = input });

        Assert.Equal(["first", "\n\n", "later"], events.OfType<TextDelta>().Select(t => t.Text));
        Assert.Equal(new Completed(0), events[^1]);
        Assert.False(input.IsOpen);
        Assert.False(input.Say("too late"));
    }

    [Fact]
    public async Task Another_flavor_ignores_the_option_and_ends_at_its_first_result()
    {
        var fake = new FakeCli(_folder).Read().Print(Open, Text("first"), Result("first"))
            .Sleep(4).Print(None, Text("later"), Result("later"));
        _ = fake.Command(new ChildInput());
        var cli = PosixCli($"cd '{_folder}'\n. ./fake.sh");
        var clock = Stopwatch.StartNew();

        var events = await Collect(Request("grok", cli, wait: true) with { Run = Request("grok", cli, true).Run! with { Deadline = new TurnDeadline(Grace) } });

        Assert.Equal(["first"], events.OfType<TextDelta>().Select(t => t.Text));
        Assert.True(clock.Elapsed < TimeSpan.FromSeconds(3), $"took {clock.Elapsed}");
    }
}
