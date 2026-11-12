using D3sk.AgentCli.Specs.Cursor;

namespace D3sk.AgentCli.Tests.Specs.Cursor;

public class CursorArgvTests
{
    private static List<string> Build(Func<CursorArgvRequest, CursorArgvRequest>? tweak = null)
    {
        var r = new CursorArgvRequest { Binary = "/bin/agent", Prompt = "hi" };
        return CursorArgv.Build(tweak?.Invoke(r) ?? r);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Argv_starts_with_the_prompt_and_ends_with_the_extra_args()
    {
        var argv = Build(r => r with { ResumeId = "abc", CliArgs = ["--model", "auto"] });
        Assert.Equal(["/bin/agent", "-p", "hi"], argv.Take(3));
        Assert.Contains("--stream-partial-output", argv);
        Assert.Contains("--trust", argv);
        Assert.Contains("--force", argv);
        Assert.Equal("abc", argv[argv.IndexOf("--resume") + 1]);
        Assert.DoesNotContain("--allowedTools", argv);
        Assert.Equal(["--model", "auto"], argv.TakeLast(2));
    }

    [Theory]
    [Trait("Category", "Preserve")]
    [InlineData("plan", false)]
    [InlineData("manual", false)]
    [InlineData("", false)]
    [InlineData(null, true)]
    [InlineData("bypassPermissions", true)]
    public void Plan_manual_and_unknown_modes_leave_out_force(string? mode, bool force)
    {
        var argv = Build(r => r with { PermissionMode = mode });
        Assert.Contains("--trust", argv);
        Assert.Equal(force, argv.Contains("--force"));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void A_model_becomes_one_flag_and_a_placeholder_none()
    {
        var argv = Build(r => r with { Model = "composer-2.5" });
        Assert.Equal(1, argv.Count(a => a == "--model"));
        Assert.Equal("composer-2.5", argv[argv.IndexOf("--model") + 1]);
        Assert.DoesNotContain("--model", Build(r => r with { Model = "Cursor Agent" }));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void A_model_id_starting_with_a_dash_is_refused() =>
        Assert.Throws<ArgumentException>(() => Build(r => r with { Model = "--yolo" }));

    [Fact]
    [Trait("Category", "Preserve")]
    public void The_system_text_goes_ahead_of_the_first_prompt_only()
    {
        Assert.Equal("sys\n\nhi", CursorArgv.ComposePrompt("hi", "sys", null));
        Assert.Equal("hi", CursorArgv.ComposePrompt("hi", "sys", "r1"));
        Assert.Equal("hi", CursorArgv.ComposePrompt("hi", "", null));
    }
}
