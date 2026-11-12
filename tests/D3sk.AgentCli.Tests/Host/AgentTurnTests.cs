using System.Text.Json.Nodes;
using D3sk.AgentCli.ChildEnv;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Host;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Tests.Output.Common;

namespace D3sk.AgentCli.Tests.Host;

/// <summary>A turn through the host against a fake CLI: a POSIX shell script (these tests skip on Windows).</summary>
public sealed class AgentTurnTests : IDisposable
{
    private static readonly Dictionary<string, string> HostEnv = new() { ["PATH"] = "/usr/bin:/bin", ["HOME"] = "/tmp" };

    private readonly string _folder = Directory.CreateTempSubdirectory("d3sk-host-").FullName;

    public void Dispose() => Directory.Delete(_folder, true);

    private string Cli(string body, string name = "fake")
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "the fake CLI is a POSIX shell script");
        var path = Path.Combine(_folder, name);
        File.WriteAllText(path, "#!/bin/sh\n" + body + "\n");
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        return path;
    }

    private static AgentTurnRequest Turn(string command, string? binary, bool activity = true) => new()
    {
        Command = command,
        Prompt = "hi",
        Env = HostEnv,
        Binary = binary,
        BinaryResolver = _ => null,
        Activity = activity,
        NoGuard = true, // these tests look at the bare turn; Host/AgentTurnWiringTests holds the guarded one
        NoWebScout = true,
        NoSecurityLog = true,
        Run = new ChildRunOptions { ExitGrace = TimeSpan.FromMilliseconds(300), ExitPoll = TimeSpan.FromMilliseconds(50) },
    };

    private static async Task<List<StreamEvent>> Collect(AgentTurnRequest request)
    {
        var events = new List<StreamEvent>();
        await foreach (var e in AgentTurn.RunAsync(request, TestContext.Current.CancellationToken))
        {
            events.Add(e);
        }
        return events;
    }

    private const string ClaudeText =
        "echo '{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s1\"}'\n" +
        "echo '{\"type\":\"stream_event\",\"event\":{\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"pong\"}}}'";

    /// <summary>Writes the child's environment to a file, then answers like Claude.</summary>
    private string EnvProbe(string answer = ClaudeText) => $"env > '{Path.Combine(_folder, "env.txt")}'\n{answer}";

    private Dictionary<string, string> ChildEnvironmentSeen() => File.ReadAllLines(Path.Combine(_folder, "env.txt"))
        .Select(l => l.Split('=', 2)).Where(p => p.Length == 2).GroupBy(p => p[0]).ToDictionary(g => g.Key, g => g.First()[1]);

    [Theory]
    [Trait("Category", "Preserve")]
    [InlineData("claude", "claude__live_thinking_then_text")]
    [InlineData("claude", "claude__thinking_tools_text")]
    [InlineData("claude", "claude__oauth_expired")]
    [InlineData("agent", "agent__thinking_tools_text")]
    [InlineData("agy", "agy__tool_steps")]
    [InlineData("copilot", "copilot__reasoning_tools_text")]
    [InlineData("grok", "grok__cancelled_by_itself")]
    [InlineData("grok", "grok__tool_output_unwrapped")]
    [InlineData("opencode", "opencode__provider_error")]
    [InlineData("opencode", "opencode__reasoning_tools_paragraphs")]
    public async Task A_capture_run_through_the_host_equals_its_expected_events_with_the_completion(string command, string capture)
    {
        var cli = Cli($"cat '{Path.Combine(StreamCaptures.Folder, capture + ".jsonl")}'");
        var expected = File.ReadAllLines(Path.Combine(StreamCaptures.Folder, capture + ".expected.jsonl"))
            .Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!.ToJsonString()).ToList();

        var events = await Collect(Turn(command, cli));

        Assert.Equal(expected, events.Select(e => StreamCaptures.Record(e).ToJsonString()));
    }

    [Fact]
    public async Task Without_activity_only_text_and_the_session_come_out()
    {
        var cli = Cli($"cat '{Path.Combine(StreamCaptures.Folder, "claude__thinking_tools_text.jsonl")}'");

        var events = await Collect(Turn("claude", cli, activity: false));

        Assert.DoesNotContain(events, e => e is ThinkingDelta or ToolCall or ToolResult);
        Assert.Contains(events, e => e is TextDelta);
        Assert.Equal(new Completed(0), events[^1]);
    }

    [Fact]
    public async Task A_missing_binary_is_one_not_found_error_with_the_install_hint_and_no_completion()
    {
        var events = await Collect(Turn("gemini", null));

        var error = Assert.IsType<StreamError>(Assert.Single(events));
        Assert.Equal("not_found", error.Code);
        Assert.Contains("CLI agent binary not found: gemini", error.Message);
        Assert.Contains("npm install -g @google/gemini-cli", error.Message);
    }

    [Fact]
    public async Task An_unknown_command_without_a_binary_gets_a_generic_hint()
    {
        var error = Assert.IsType<StreamError>(Assert.Single(await Collect(Turn("mytool", null))));
        Assert.Contains("Install `mytool` and ensure it is on PATH.", error.Message);
    }

    [Fact]
    public async Task The_binary_is_resolved_through_the_resolver_when_none_is_given()
    {
        var cli = Cli(ClaudeText);
        var request = Turn("claude", null) with { BinaryResolver = c => c == "claude" ? cli : null };

        var events = await Collect(request);

        Assert.Contains(new TextDelta("pong"), events);
    }

    [Fact]
    [Trait("Category", "Security")]
    public void A_turn_without_the_hosts_environment_is_refused()
    {
        Assert.Throws<MissingChildEnvironmentException>(() => AgentTurn.RunAsync(Turn("claude", "/bin/true") with { Env = new Dictionary<string, string>() }, TestContext.Current.CancellationToken));
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task The_child_gets_only_the_hosts_environment_without_the_bridge_tokens_or_the_transcript_killers()
    {
        var cli = Cli(EnvProbe());
        var request = Turn("claude", cli) with
        {
            Env = new Dictionary<string, string>(HostEnv)
            {
                ["D3SK_KEEP"] = "kept", ["BRIDGE_TOKEN"] = "secret", ["BRIDGE_OWNER_TOKEN"] = "secret", ["CLAUDE_CODE_SIMPLE"] = "1",
            },
        };
        Environment.SetEnvironmentVariable("D3SK_LEAK", "parent");
        try
        {
            Assert.Contains(new TextDelta("pong"), await Collect(request));
        }
        finally
        {
            Environment.SetEnvironmentVariable("D3SK_LEAK", null);
        }

        var seen = ChildEnvironmentSeen();
        Assert.Equal("kept", seen["D3SK_KEEP"]);
        Assert.DoesNotContain("BRIDGE_TOKEN", seen.Keys);
        Assert.DoesNotContain("BRIDGE_OWNER_TOKEN", seen.Keys);
        Assert.DoesNotContain("CLAUDE_CODE_SIMPLE", seen.Keys);
        Assert.DoesNotContain("D3SK_LEAK", seen.Keys);
        Assert.Equal("0", seen["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"]);
    }

    [Fact]
    public async Task A_host_extra_variable_wins_and_the_hosts_wait_ceiling_is_kept()
    {
        var request = Turn("claude", Cli(EnvProbe())) with
        {
            ExtraEnv = new Dictionary<string, string> { ["X"] = "extra", ["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = "5000" },
        };

        await Collect(request);

        var seen = ChildEnvironmentSeen();
        Assert.Equal("extra", seen["X"]);
        Assert.Equal("5000", seen["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"]);
    }

    [Fact]
    public async Task OpenCode_gets_the_chunk_timeout_and_the_project_in_its_environment()
    {
        var answer = "echo '{\"type\":\"text\",\"sessionID\":\"ses_1\",\"part\":{\"type\":\"text\",\"text\":\"ok\"}}'";
        var request = Turn("opencode", Cli(EnvProbe(answer))) with { Model = "openrouter/some/model", Cwd = _folder };

        var events = await Collect(request);

        Assert.Contains(new TextDelta("ok"), events);
        var seen = ChildEnvironmentSeen();
        Assert.Equal(_folder, seen["PWD"]);
        Assert.Contains("\"chunkTimeout\":120000", seen["OPENCODE_CONFIG_CONTENT"]);
        Assert.DoesNotContain("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", seen.Keys);
        Assert.Equal(new Completed(0), events[^1]);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task Cursors_name_resolving_to_Groks_binary_is_refused_not_run()
    {
        var folder = Directory.CreateDirectory(Path.Combine(_folder, ".grok", "bin")).FullName;
        var marker = Path.Combine(_folder, "ran");
        var cli = Cli($"touch '{marker}'", Path.Combine(".grok", "bin", "agent"));
        Assert.Equal(Path.Combine(folder, "agent"), cli);

        var error = Assert.IsType<StreamError>(Assert.Single(await Collect(Turn("agent", cli))));

        Assert.Equal("cli_collision", error.Code);
        Assert.Contains("Grok CLI's own binary", error.Message);
        Assert.False(File.Exists(marker));
    }

    [Fact]
    public async Task A_failing_child_with_no_output_reports_its_stderr_then_its_exit_code()
    {
        var cli = Cli("echo 'quota exceeded' >&2; exit 3");

        var events = await Collect(Turn("claude", cli));

        Assert.Equal([new StreamError("quota exceeded"), new Completed(3)], events);
    }

    [Fact]
    public async Task A_JSON_error_on_stderr_is_unwrapped_to_its_message()
    {
        var cli = Cli("echo '{\"session_id\":\"x\",\"error\":{\"message\":\"Please log in\",\"code\":41}}' >&2; exit 1");

        var events = await Collect(Turn("gemini", cli));

        Assert.Equal([new StreamError("Please log in"), new Completed(1)], events);
    }

    [Fact]
    public async Task A_child_that_exits_cleanly_with_nothing_says_so()
    {
        var events = await Collect(Turn("claude", Cli("exit 0")));

        var error = Assert.IsType<StreamError>(events[0]);
        Assert.Equal("empty_output", error.Code);
        Assert.Equal(new Completed(0), events[1]);
    }

    [Fact]
    public async Task A_clean_exit_with_only_stderr_surfaces_it()
    {
        var events = await Collect(Turn("agy", Cli("echo 'rate limited' >&2")));

        Assert.Equal([new StreamError("rate limited"), new Completed(0)], events);
    }

    [Fact]
    public async Task A_missing_program_inside_a_resolved_binary_is_a_spawn_error_and_no_completion()
    {
        var error = Assert.IsType<StreamError>(Assert.Single(await Collect(Turn("claude", Path.Combine(_folder, "absent")))));
        Assert.Equal("not_found", error.Code);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task Cancelling_stops_the_child_and_throws()
    {
        var pidFile = Path.Combine(_folder, "pid");
        var cli = Cli($"echo $$ > '{pidFile}'\n" + ClaudeText + "\nsleep 30");
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
        {
            await foreach (var e in AgentTurn.RunAsync(Turn("claude", cli), cts.Token))
            {
                if (e is TextDelta)
                {
                    await cts.CancelAsync();
                }
            }
        });

        var pid = int.Parse((await File.ReadAllTextAsync(pidFile, TestContext.Current.CancellationToken)).Trim());
        for (var i = 0; i < 50 && Directory.Exists($"/proc/{pid}") && !File.ReadAllText($"/proc/{pid}/stat").Contains(") Z "); i++)
        {
            await Task.Delay(100, TestContext.Current.CancellationToken);
        }
        Assert.False(Directory.Exists($"/proc/{pid}") && !File.ReadAllText($"/proc/{pid}/stat").Contains(") Z "), "the child survived Stop");
    }

    [Fact]
    public async Task A_long_prompt_travels_on_stdin_for_claude_and_grok_only_when_it_is_too_long()
    {
        var cli = Cli("cat >&2; exit 4"); // echoes stdin as the error text
        var big = new string('x', 300_000);

        var viaStdin = await Collect(Turn("claude", cli) with { Prompt = big });
        var tooLong = await Collect(Turn("agent", cli) with { Prompt = big });

        var echoed = Assert.IsType<StreamError>(viaStdin[0]).Message; // stderr keeps its last 256 KiB
        Assert.Equal(new string('x', 262_144), echoed);
        Assert.Equal("prompt_too_long", Assert.IsType<StreamError>(Assert.Single(tooLong)).Code);
    }
}
