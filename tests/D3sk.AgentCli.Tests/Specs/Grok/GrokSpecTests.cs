using D3sk.AgentCli.Specs.Grok;

namespace D3sk.AgentCli.Tests.Specs.Grok;

public class GrokSpecTests
{
    private static List<string> Argv(string? mode) =>
        GrokArgv.Build(new GrokArgvRequest { Binary = "grok", Prompt = "hi", PermissionMode = mode });

    private static string After(List<string> argv, string flag) => argv[argv.IndexOf(flag) + 1];

    [Fact]
    [Trait("Category", "Security")]
    public void Plan_and_ask_are_read_only()
    {
        foreach (var mode in new[] { "plan", "manual" })
        {
            var argv = Argv(mode);
            Assert.All(After(argv, "--tools").Split(','), t =>
                Assert.Contains(t, new[] { "read_file", "list_dir", "grep", "todo_write", "web_search", "web_fetch" }));
            Assert.Equal("MCPTool", After(argv, "--deny"));
            Assert.Equal("Agent", After(argv, "--disallowed-tools"));
            Assert.DoesNotContain("--permission-mode", argv);
        }
    }

    [Fact]
    [Trait("Category", "Security")]
    public void An_unknown_mode_is_plan()
    {
        Assert.Contains("--tools", Argv("Plan"));
        Assert.Contains("--tools", Argv(""));
    }

    [Fact]
    public void Edit_modes_deny_the_shell_and_mcp()
    {
        foreach (var mode in new[] { "acceptEdits", "dontAsk", null })
        {
            var argv = Argv(mode);
            Assert.Equal("acceptEdits", After(argv, "--permission-mode"));
            var denies = argv.Select((a, i) => (a, i)).Where(x => x.a == "--deny").Select(x => argv[x.i + 1]).ToList();
            Assert.Equal(["Bash", "MCPTool"], denies);
            Assert.DoesNotContain("--tools", argv);
        }
    }

    [Fact]
    public void Bypass_approves_everything()
    {
        var argv = Argv("bypassPermissions");
        Assert.Equal("bypassPermissions", After(argv, "--permission-mode"));
        Assert.DoesNotContain("--deny", argv);
    }

    [Fact]
    public void Auto_approves_tools_instead_of_waiting_for_a_click()
    {
        var argv = Argv("auto");
        Assert.Contains("--always-approve", argv);
        Assert.DoesNotContain("--permission-mode", argv);
        Assert.DoesNotContain("--deny", argv);
    }

    [Fact]
    public void Resume_is_a_flag()
    {
        var argv = GrokArgv.Build(new GrokArgvRequest { Binary = "grok", Prompt = "hi", ResumeId = "01a0a000-0000-7000-8000-000000000001" });
        Assert.Equal("01a0a000-0000-7000-8000-000000000001", After(argv, "--resume"));
    }

    [Fact]
    public void A_long_prompt_travels_on_stdin()
    {
        var argv = GrokArgv.Build(new GrokArgvRequest { Binary = "grok", Prompt = "a long prompt", PromptOnStdin = true });
        Assert.Equal("-", After(argv, "-p"));
        Assert.DoesNotContain("a long prompt", argv);
    }

    [Fact]
    public void Streams_partial_messages()
    {
        Assert.Equal(["grok", "-p", "hi", "--output-format", "streaming-messages-json", "--include-partial-messages"],
            Argv("bypassPermissions").Take(6));
    }

    [Theory]
    [InlineData("grok-4.6-high", new[] { "--model", "grok-4.6", "--reasoning-effort", "high" })]
    [InlineData("grok-4.6-low", new[] { "--model", "grok-4.6", "--reasoning-effort", "low" })]
    [InlineData("grok-4.5", new[] { "--model", "grok-4.5" })]
    [InlineData("default", new string[0])]
    [InlineData(" ", new string[0])]
    public void Model_args(string model, string[] expected) => Assert.Equal(expected, GrokArgv.ModelArgs(model));

    [Fact]
    [Trait("Category", "Security")]
    public void A_model_id_that_looks_like_a_flag_is_refused()
    {
        Assert.Throws<ArgumentException>(() => GrokArgv.ModelArgs("--yolo"));
        Assert.Throws<ArgumentException>(() => GrokArgv.Build(new GrokArgvRequest { Binary = "grok", Model = " -x" }));
    }

    [Fact]
    public void Gets_no_claude_deny_rules() => Assert.DoesNotContain("--disallowedTools", Argv(null));

    [Fact]
    public void Path_wins_and_the_exe_twin_is_tried()
    {
        var sep = Path.PathSeparator;
        var exe = Path.Combine("/b", "grok") + ".exe";
        Assert.Equal(Path.Combine("/a", "grok"), GrokDiscovery.Resolve($"/a{sep}/b", p => p == Path.Combine("/a", "grok") || p == exe));
        Assert.Equal(exe, GrokDiscovery.Resolve("/b", p => p == exe));
        Assert.Null(GrokDiscovery.Resolve("/a", _ => false));
    }

    [Fact]
    public void A_non_executable_file_is_not_usable()
    {
        if (OperatingSystem.IsWindows()) return;
        var dir = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var plain = Path.Combine(dir, "grok");
            File.WriteAllText(plain, "x");
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            Assert.Null(GrokDiscovery.Resolve(dir));
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Assert.Equal(plain, GrokDiscovery.Resolve(dir));
        }
        finally { Directory.Delete(dir, true); }
    }
}
