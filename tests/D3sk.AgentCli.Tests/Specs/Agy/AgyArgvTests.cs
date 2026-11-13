using D3sk.AgentCli.Specs.Agy;

namespace D3sk.AgentCli.Tests.Specs.Agy;

public class AgyArgvTests
{
    private static List<string> Build(string? model = null, string? resume = null, string? mode = null, string? cwd = null) =>
        AgyArgv.Build(new AgyArgvRequest { Binary = "/bin/agy", Prompt = "hi there", Model = model, ResumeId = resume, PermissionMode = mode, Cwd = cwd });

    private static string After(List<string> argv, string flag) => argv[argv.IndexOf(flag) + 1];

    [Fact]
    public void Default_turn_is_print_stream_json_accept_edits_without_add_dir()
    {
        var argv = Build();
        Assert.Equal(["/bin/agy", "-p", "hi there"], argv.Take(3));
        Assert.Equal("stream-json", After(argv, "--output-format"));
        Assert.Equal("accept-edits", After(argv, "--mode"));
        Assert.DoesNotContain("--add-dir", argv);
    }

    [Fact]
    public void Cwd_is_attached_with_add_dir()
    {
        Assert.Equal(@"C:\Work\Project", After(Build(cwd: @"C:\Work\Project"), "--add-dir"));
    }

    [Fact]
    public void Model_flag_is_passed_and_placeholders_are_dropped()
    {
        Assert.Equal("gemini-3.1-pro", After(Build(model: "gemini-3.1-pro"), "--model"));
        Assert.DoesNotContain("--model", Build(model: "default"));
        Assert.DoesNotContain("--model", Build(model: "Google Antigravity"));
    }

    [Fact]
    public void Resume_uses_conversation()
    {
        Assert.Equal("78e0306d-c270-4cab-a23a-74f338f1747a", After(Build(resume: "78e0306d-c270-4cab-a23a-74f338f1747a"), "--conversation"));
        Assert.DoesNotContain("--conversation", Build());
    }

    [Theory]
    [InlineData("plan", "plan")]
    [InlineData("manual", "accept-edits")]
    [InlineData("acceptEdits", "accept-edits")]
    [InlineData("auto", "auto")]
    [InlineData("dontAsk", "auto")]
    [InlineData(null, "accept-edits")]
    [InlineData("nonsense", "plan")]
    [InlineData("", "plan")]
    public void Permission_mode_maps_to_mode(string? mode, string expected)
    {
        var argv = Build(mode: mode);
        Assert.Equal(expected, After(argv, "--mode"));
        Assert.DoesNotContain("--dangerously-skip-permissions", argv);
    }

    [Fact]
    [Trait("Category", "Security")]
    public void Only_bypass_adds_the_skip_flag()
    {
        Assert.Equal(["--mode", "accept-edits", "--dangerously-skip-permissions"], AgyArgv.PermissionArgs("bypassPermissions"));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void A_model_id_that_looks_like_a_flag_is_refused()
    {
        Assert.Throws<ArgumentException>(() => Build(model: "--yolo"));
        Assert.Throws<ArgumentException>(() => Build(model: " -x"));
    }

    [Fact]
    public void Cli_args_come_last_and_no_claude_rules_are_added()
    {
        var argv = AgyArgv.Build(new AgyArgvRequest { Binary = "b", CliArgs = ["--x"], Cwd = "/p" });
        Assert.Equal("--x", argv[^1]);
        Assert.DoesNotContain("--disallowedTools", argv);
    }

    [Fact]
    public void Spec_names_the_cli_and_starts_with_default()
    {
        Assert.Equal("agy", AgySpec.Command);
        Assert.Equal("antigravity", AgySpec.Flavor);
        Assert.Equal("default", AgySpec.Models[0]);
    }
}
