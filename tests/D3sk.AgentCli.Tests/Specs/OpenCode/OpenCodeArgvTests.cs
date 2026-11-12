using System.Text.Json.Nodes;
using D3sk.AgentCli.Specs.OpenCode;

namespace D3sk.AgentCli.Tests.Specs.OpenCode;

public class OpenCodeArgvTests
{
    private static List<string> Build(Func<OpenCodeArgvRequest, OpenCodeArgvRequest>? tweak = null)
    {
        var request = new OpenCodeArgvRequest { Binary = "opencode", Prompt = "-hi" };
        return OpenCodeArgv.Build(tweak?.Invoke(request) ?? request);
    }

    [Fact]
    public void Runs_headless_without_a_dir_flag_and_the_prompt_after_dashes()
    {
        var argv = Build(r => r with { Model = "openrouter/stealth/union-alpha" });
        Assert.Equal(["opencode", "run", "--format", "json", "--thinking"], argv.Take(5));
        Assert.DoesNotContain("--dir", argv);
        Assert.Equal("openrouter/stealth/union-alpha", argv[argv.IndexOf("--model") + 1]);
        Assert.Equal(["--", "-hi"], argv.TakeLast(2));
    }

    [Theory]
    [InlineData("plan")]
    [InlineData("manual")]
    [InlineData("nonsense")]
    public void Plan_manual_and_unknown_modes_use_the_plan_agent(string mode)
    {
        var argv = Build(r => r with { PermissionMode = mode });
        Assert.Equal("plan", argv[argv.IndexOf("--agent") + 1]);
        Assert.DoesNotContain("--auto", argv);
    }

    [Theory]
    [InlineData("acceptEdits")]
    [InlineData("auto")]
    [InlineData("dontAsk")]
    [InlineData(null)]
    public void Edit_modes_use_the_build_agent(string? mode)
    {
        var argv = Build(r => r with { PermissionMode = mode });
        Assert.DoesNotContain("--agent", argv);
        Assert.DoesNotContain("--auto", argv);
    }

    [Fact]
    public void Bypass_auto_approves()
    {
        var argv = Build(r => r with { PermissionMode = "bypassPermissions" });
        Assert.Contains("--auto", argv);
        Assert.DoesNotContain("--agent", argv);
    }

    [Fact]
    public void Resume_is_a_session_flag_and_cli_args_come_before_the_prompt()
    {
        var argv = Build(r => r with { ResumeId = "ses_f504cd75fffehYULWTaZuNfg2b", CliArgs = ["--x"] });
        Assert.Equal("ses_f504cd75fffehYULWTaZuNfg2b", argv[argv.IndexOf("--session") + 1]);
        Assert.Equal(["--x", "--", "-hi"], argv.TakeLast(3));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void A_model_id_that_looks_like_a_flag_is_refused()
    {
        Assert.Throws<ArgumentException>(() => Build(r => r with { Model = " -x" }));
        Assert.Throws<ArgumentException>(() => Build(r => r with { Model = "--yolo" }));
    }

    [Fact]
    public void Spec_names_the_cli_and_defaults_to_the_first_model()
    {
        Assert.Equal("opencode", OpenCodeSpec.Command);
        Assert.Equal("opencode", OpenCodeSpec.Flavor);
        Assert.Equal("openrouter/stealth/crouton-alpha", OpenCodeSpec.Models[0]);
        Assert.Equal(22, OpenCodeSpec.Models.Count);
    }

    [Fact]
    public void Directory_publishes_the_project_as_pwd()
    {
        var env = new Dictionary<string, string> { ["PWD"] = "/wrong" };
        OpenCodeEnvironment.Directory(env, "/code/app");
        Assert.Equal("/code/app", env["PWD"]);
        var untouched = new Dictionary<string, string>();
        OpenCodeEnvironment.Directory(untouched, null);
        Assert.Empty(untouched);
    }

    [Fact]
    public void Gets_a_chunk_timeout_for_the_model_provider()
    {
        var config = JsonNode.Parse(OpenCodeEnvironment.ConfigContent("openrouter/stealth/union-alpha", null)!)!;
        Assert.Equal(OpenCodeEnvironment.ChunkTimeoutMs, (int)config["provider"]!["openrouter"]!["options"]!["chunkTimeout"]!);
    }

    [Fact]
    public void Chunk_timeout_merges_with_the_host_config()
    {
        var host = """{"provider":{"openrouter":{"options":{"baseURL":"http://proxy"}}},"share":"disabled"}""";
        var config = JsonNode.Parse(OpenCodeEnvironment.ConfigContent("openrouter/x/y", host)!)!;
        Assert.Equal("disabled", (string)config["share"]!);
        var options = config["provider"]!["openrouter"]!["options"]!;
        Assert.Equal("http://proxy", (string)options["baseURL"]!);
        Assert.Equal(OpenCodeEnvironment.ChunkTimeoutMs, (int)options["chunkTimeout"]!);
    }

    [Fact]
    public void Config_content_leaves_host_choices_alone()
    {
        var chosen = """{"provider":{"opencode":{"options":{"chunkTimeout":5000}}}}""";
        Assert.Null(OpenCodeEnvironment.ConfigContent("opencode/big-pickle", chosen));
        Assert.Null(OpenCodeEnvironment.ConfigContent("opencode/big-pickle", "not json"));
        Assert.Null(OpenCodeEnvironment.ConfigContent("opencode/big-pickle", "[1]"));
        Assert.Null(OpenCodeEnvironment.ConfigContent("opencode/big-pickle", """{"provider":[]}"""));
        Assert.Null(OpenCodeEnvironment.ConfigContent("big-pickle", null));
        Assert.Null(OpenCodeEnvironment.ConfigContent(null, null));
    }
}
