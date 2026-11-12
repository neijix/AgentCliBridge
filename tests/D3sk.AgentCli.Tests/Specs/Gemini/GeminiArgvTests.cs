using D3sk.AgentCli.Specs.Gemini;

namespace D3sk.AgentCli.Tests.Specs.Gemini;

public class GeminiArgvTests
{
    private static List<string> Build(string? model = null, string? mode = null, params string[] cliArgs) =>
        GeminiArgv.Build(new GeminiArgvRequest { Binary = "/bin/gemini", Prompt = "hi", Model = model, PermissionMode = mode, CliArgs = cliArgs });

    private static string After(List<string> argv, string flag) => argv[argv.IndexOf(flag) + 1];

    [Fact]
    [Trait("Category", "Preserve")]
    public void Default_argv_streams_json_and_auto_approves()
    {
        var argv = Build("gemini-2.5-flash");
        Assert.Equal(["/bin/gemini", "-p", "hi"], argv.Take(3));
        Assert.Equal("stream-json", After(argv, "--output-format"));
        Assert.Contains("--skip-trust", argv);
        Assert.Equal("yolo", After(argv, "--approval-mode"));
        Assert.Equal("gemini-2.5-flash", After(argv, "--model"));
    }

    [Theory]
    [Trait("Category", "Security")]
    [InlineData("plan", "plan")]
    [InlineData("manual", "plan")]
    [InlineData("", "plan")]
    [InlineData("nonsense", "plan")]
    [InlineData(null, "yolo")]
    [InlineData("acceptEdits", "yolo")]
    [InlineData("auto", "yolo")]
    [InlineData("bypassPermissions", "yolo")]
    public void Permission_mode_maps_to_the_approval_mode_and_unknown_stays_read_only(string? mode, string expected) =>
        Assert.Equal(expected, After(Build(mode: mode), "--approval-mode"));

    [Fact]
    public void Placeholder_model_adds_no_flag_and_a_flag_like_model_is_refused()
    {
        Assert.DoesNotContain("--model", Build("Gemini CLI"));
        Assert.DoesNotContain("--model", Build("default"));
        Assert.Throws<ArgumentException>(() => Build("--yolo"));
        Assert.Throws<ArgumentException>(() => Build(" -x"));
    }

    [Fact]
    public void Extra_args_come_last_and_there_is_no_resume_flag() =>
        Assert.Equal(["--extra"], Build(null, "plan", "--extra").TakeLast(1));

    [Fact]
    public void System_text_goes_ahead_of_the_prompt_on_a_first_turn_only()
    {
        Assert.Equal("sys\n\nhi", GeminiArgv.ComposePrompt("hi", "sys", null));
        Assert.Equal("hi", GeminiArgv.ComposePrompt("hi", "sys", "r1"));
        Assert.Equal("hi", GeminiArgv.ComposePrompt("hi", "", null));
    }

    [Fact]
    public void Spec_names_the_cli()
    {
        Assert.Equal("gemini", GeminiSpec.Command);
        Assert.Equal("gemini-3.1-pro-preview", GeminiSpec.Models[0]);
    }
}
