using System.Diagnostics;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Runner;

/// <summary>The runner against a tiny fake child: a POSIX shell script (these tests skip on Windows).</summary>
public class ChildTurnTests
{
    private static readonly Dictionary<string, string> Env = new() { ["PATH"] = "/usr/bin:/bin", ["D3SK_TEST"] = "1" };

    private static ChildCommand Sh(string script, ChildInput? live = null, string? stdin = null,
        Dictionary<string, string>? env = null) => new()
    {
        FileName = "/bin/sh",
        Arguments = ["-c", script],
        Environment = env ?? Env,
        LiveInput = live,
        StdinText = stdin,
    };

    private static ChildRunOptions Fast(TimeSpan? timeout = null, TurnDeadline? deadline = null) => new()
    {
        Timeout = timeout,
        Deadline = deadline,
        ExitGrace = TimeSpan.FromMilliseconds(300),
        ExitPoll = TimeSpan.FromMilliseconds(50),
    };

    private static async Task<List<ChildEvent>> Collect(ChildCommand c, ChildRunOptions? o = null)
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "the fake child is a POSIX shell script");
        var all = new List<ChildEvent>();
        await foreach (var e in ChildTurn.RunAsync(c, o ?? Fast(), TestContext.Current.CancellationToken))
        {
            all.Add(e);
        }
        return all;
    }

    private static bool Alive(int pid)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            return !p.HasExited && !File.ReadAllText($"/proc/{pid}/stat").Contains(") Z ");
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or IOException)
        {
            return false;
        }
    }

    [Fact]
    public async Task Lines_arrive_in_order_even_past_64KiB_and_the_exit_follows()
    {
        var events = await Collect(Sh("printf 'a\\n'; head -c 200000 /dev/zero | tr '\\0' x; printf '\\nlast'; exit 0"));
        var lines = events.OfType<ChildLine>().ToList();
        Assert.Equal(3, lines.Count);
        Assert.Equal("a\n", lines[0].Text);
        Assert.Equal(200001, lines[1].Bytes.Length);
        Assert.Equal("last", lines[2].Text);
        Assert.Equal(new ChildExited(0, "", false), Assert.IsType<ChildExited>(events[^1]));
    }

    [Fact]
    public async Task A_child_that_dies_without_output_is_an_error_event_with_its_stderr()
    {
        var events = await Collect(Sh("echo boom >&2; exit 3"));
        var error = Assert.IsType<ChildError>(events[0]);
        Assert.Equal("child_died", error.Code);
        Assert.Equal("boom", error.Message);
        Assert.Equal(3, Assert.IsType<ChildExited>(events[^1]).ExitCode);
    }

    [Fact]
    public async Task A_child_killed_by_a_signal_is_an_error_event_not_a_hang()
    {
        var events = await Collect(Sh("kill -9 $$"));
        Assert.Equal("child_died", Assert.IsType<ChildError>(events[0]).Code);
        Assert.NotEqual(0, Assert.IsType<ChildExited>(events[^1]).ExitCode);
    }

    [Fact]
    public async Task A_missing_program_is_not_found()
    {
        var events = await Collect(new ChildCommand { FileName = "/nonexistent/agent-cli", Environment = Env });
        var error = Assert.IsType<ChildError>(Assert.Single(events));
        Assert.Equal("not_found", error.Code);
    }

    [Fact]
    public async Task The_child_gets_only_the_environment_it_was_given()
    {
        Environment.SetEnvironmentVariable("D3SK_PARENT_ONLY", "leak");
        var events = await Collect(Sh("echo \"[$D3SK_PARENT_ONLY][$D3SK_TEST]\""));
        Assert.Equal("[][1]\n", events.OfType<ChildLine>().Single().Text);
    }

    [Fact]
    public async Task Stdin_text_is_delivered_and_closed_otherwise_stdin_is_empty()
    {
        var withText = await Collect(Sh("cat", stdin: "long prompt"));
        Assert.Equal("long prompt", withText.OfType<ChildLine>().Single().Text);
        var without = await Collect(Sh("cat; echo end"));
        Assert.Equal("end\n", without.OfType<ChildLine>().Single().Text);
    }

    [Fact]
    public async Task Live_input_reaches_the_child_and_closes_with_the_turn()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        var live = new ChildInput();
        Assert.False(live.WriteLine("before the child started"));
        var lines = new List<string>();
        await foreach (var e in ChildTurn.RunAsync(Sh("echo ready; read a; echo got:$a", live), Fast(), TestContext.Current.CancellationToken))
        {
            if (e is ChildLine l)
            {
                lines.Add(l.Text.Trim());
                if (lines.Count == 1)
                {
                    Assert.True(live.WriteLine("two"));
                }
            }
        }
        Assert.Equal(["ready", "got:two"], lines);
        Assert.False(live.WriteLine("after the turn"));
    }

    [Fact]
    public async Task Cancelling_kills_the_whole_tree_and_throws()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);
        int grandchild = 0;
        var run = async () =>
        {
            await foreach (var e in ChildTurn.RunAsync(Sh("sleep 60 & echo $!; wait"), Fast(), cts.Token))
            {
                if (e is ChildLine l)
                {
                    grandchild = int.Parse(l.Text.Trim());
                    Assert.True(Alive(grandchild));
                    await cts.CancelAsync();
                }
            }
        };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(run);
        await WaitDead(grandchild);
    }

    [Fact]
    public async Task Abandoning_the_enumeration_kills_the_tree()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        int grandchild = 0;
        await foreach (var e in ChildTurn.RunAsync(Sh("sleep 60 & echo $!; wait"), Fast(), TestContext.Current.CancellationToken))
        {
            grandchild = int.Parse(((ChildLine)e).Text.Trim());
            break;
        }
        await WaitDead(grandchild);
    }

    [Fact]
    public async Task A_clean_finish_leaves_the_child_it_started_running()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        var events = await Collect(Sh("sleep 30 >/dev/null 2>&1 </dev/null & echo $!"));
        var pid = int.Parse(events.OfType<ChildLine>().Single().Text.Trim());
        try
        {
            Assert.True(Alive(pid));
            Assert.Equal(0, Assert.IsType<ChildExited>(events[^1]).ExitCode);
        }
        finally
        {
            Process.GetProcessById(pid).Kill();
        }
    }

    [Fact]
    public async Task The_grace_after_the_result_ends_the_run_and_stops_a_lingering_cli()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        var deadline = new TurnDeadline(TimeSpan.FromMilliseconds(300));
        var sw = Stopwatch.StartNew();
        var events = new List<ChildEvent>();
        await foreach (var e in ChildTurn.RunAsync(Sh("echo result; sleep 30"), Fast(deadline: deadline), TestContext.Current.CancellationToken))
        {
            events.Add(e);
            if (e is ChildLine)
            {
                deadline.Start(); // the parser saw the result event
            }
        }
        Assert.True(sw.Elapsed < TimeSpan.FromSeconds(10), sw.Elapsed.ToString());
        var exited = Assert.IsType<ChildExited>(events[^1]);
        Assert.Equal(0, exited.ExitCode);
        Assert.True(exited.StdoutAbandoned);
    }

    [Fact]
    public async Task The_timeout_kills_the_tree_and_reports_it()
    {
        var sw = Stopwatch.StartNew();
        var events = await Collect(Sh("sleep 30"), Fast(timeout: TimeSpan.FromMilliseconds(300)));
        Assert.True(sw.Elapsed < TimeSpan.FromSeconds(10));
        Assert.Contains(events, e => e is ChildError { Code: "timeout" });
    }

    [Fact]
    public async Task A_lost_consumer_connection_is_not_a_cancel_a_slow_consumer_does_not_stop_the_child()
    {
        // The runner has no notion of a connection: only the token or abandoning the enumeration
        // stops a CLI. A consumer that is merely slow still gets every line and the exit.
        var got = new List<ChildEvent>();
        Assert.SkipWhen(OperatingSystem.IsWindows(), "POSIX shell");
        await foreach (var e in ChildTurn.RunAsync(Sh("echo one; sleep 0.3; echo two"), Fast(), TestContext.Current.CancellationToken))
        {
            got.Add(e);
            await Task.Delay(500, TestContext.Current.CancellationToken);
        }
        Assert.Equal(2, got.OfType<ChildLine>().Count());
        Assert.Equal(0, Assert.IsType<ChildExited>(got[^1]).ExitCode);
    }

    private static async Task WaitDead(int pid)
    {
        Assert.True(pid > 0);
        for (var i = 0; i < 100 && Alive(pid); i++)
        {
            await Task.Delay(50, TestContext.Current.CancellationToken);
        }
        Assert.False(Alive(pid), "the grandchild survived the kill");
    }
}
