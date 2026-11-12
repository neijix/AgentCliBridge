using D3sk.AgentCli.Specs.Copilot;

namespace D3sk.AgentCli.Tests.Specs.Copilot;

public class CopilotSpecTests
{
    private static Func<string, bool> Only(params string[] present) => p => present.Contains(p);

    [Fact]
    public void Path_wins_over_the_local_bin()
    {
        var sep = Path.PathSeparator;
        var found = CopilotDiscovery.Resolve($"/a{sep}/b", "/h", Only(Path.Combine("/h", ".local", "bin", "copilot"), Path.Combine("/b", "copilot")));
        Assert.Equal(Path.Combine("/b", "copilot"), found);
    }

    [Fact]
    public void Falls_back_to_the_local_bin_and_tries_the_exe_twin()
    {
        var local = Path.Combine("/h", ".local", "bin", "copilot");
        Assert.Equal(local, CopilotDiscovery.Resolve("/a", "/h", Only(local)));
        Assert.Equal(Path.Combine("/a", "copilot") + ".exe", CopilotDiscovery.Resolve("/a", "/h", Only(Path.Combine("/a", "copilot") + ".exe")));
        Assert.Null(CopilotDiscovery.Resolve("/a", "/h", _ => false));
    }

    [Fact]
    public void Spec_names()
    {
        Assert.Equal("copilot", CopilotSpec.Command);
        Assert.Equal("auto", CopilotSpec.Models[0]);
    }

    [Fact]
    public void Default_argv_allows_tools_and_resumes()
    {
        var argv = CopilotArgv.Build(new() { Binary = "/bin/copilot", Prompt = "hi", Model = "auto", ResumeId = "abc123" });
        Assert.Equal(["/bin/copilot", "-p", "hi"], argv.Take(3));
        Assert.Equal("json", argv[argv.IndexOf("--output-format") + 1]);
        Assert.Contains("--no-ask-user", argv);
        Assert.Contains("--resume=abc123", argv);
        Assert.Contains("--allow-all-tools", argv);
        Assert.Equal("auto", argv[argv.IndexOf("--model") + 1]);
    }

    [Fact]
    public void Plan_mode_is_read_only()
    {
        var argv = CopilotArgv.Build(new() { Binary = "b", PermissionMode = "plan" });
        Assert.Contains("--plan", argv);
        Assert.DoesNotContain("--allow-all-tools", argv);
    }

    [Fact]
    public void An_unknown_mode_becomes_plan_and_others_allow_tools()
    {
        Assert.Equal(["--plan"], CopilotArgv.PermissionArgs("Plan"));
        Assert.Equal(["--plan"], CopilotArgv.PermissionArgs(""));
        foreach (var mode in new[] { null, "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions" })
            Assert.Equal(["--allow-all-tools"], CopilotArgv.PermissionArgs(mode));
    }

    [Fact]
    public void Model_placeholders_are_dropped_and_a_flag_like_id_is_refused()
    {
        Assert.Empty(CopilotArgv.ModelArgs("default"));
        Assert.Empty(CopilotArgv.ModelArgs(null));
        Assert.Equal(["--model", "gpt-5-mini"], CopilotArgv.ModelArgs("gpt-5-mini"));
        Assert.Throws<ArgumentException>(() => CopilotArgv.ModelArgs("--yolo"));
        Assert.Throws<ArgumentException>(() => CopilotArgv.Build(new() { Binary = "b", Model = " -x" }));
    }

    [Fact]
    public void Effort_and_cli_args_come_last_and_no_claude_rules()
    {
        var argv = CopilotArgv.Build(new() { Binary = "b", Effort = "high", CliArgs = ["--x"] });
        Assert.Equal(["--reasoning-effort", "high", "--x"], argv.TakeLast(3));
        Assert.DoesNotContain("--disallowedTools", argv);
    }
}
