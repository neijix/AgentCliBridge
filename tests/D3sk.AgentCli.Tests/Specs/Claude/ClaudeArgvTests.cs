using D3sk.AgentCli.Catalog;
using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Tests.Specs.Claude;

public class ClaudeArgvTests
{
    private const string Home = "/srv/x/.agent-cli-bridge";

    private static List<string> Build(Action<ClaudeArgvRequestBuilder>? tweak = null)
    {
        var b = new ClaudeArgvRequestBuilder();
        tweak?.Invoke(b);
        return ClaudeArgv.Build(b.ToRequest());
    }

    private sealed class ClaudeArgvRequestBuilder
    {
        public ClaudeArgvRequest Request = new() { Binary = "claude", Prompt = "hi", BridgeHome = Home, AllowSudo = true };
        public void With(Func<ClaudeArgvRequest, ClaudeArgvRequest> f) => Request = f(Request);
        public ClaudeArgvRequest ToRequest() => Request;
    }

    private static string After(List<string> argv, string flag) => argv[argv.IndexOf(flag) + 1];

    [Theory]
    [InlineData(null, "acceptEdits")]
    [InlineData("plan", "plan")]
    [InlineData("bypassPermissions", "bypassPermissions")]
    [InlineData("", "plan")]
    [InlineData("Plan", "plan")]
    [InlineData("nonsense", "plan")]
    [InlineData(" auto ", "auto")]
    public void Permission_mode_is_normalized(string? input, string expected)
    {
        Assert.Equal(expected, ClaudeArgv.NormalizePermissionMode(input));
        Assert.Equal(["--permission-mode", expected], ClaudeArgv.PermissionArgs(input).Take(2));
    }

    [Fact]
    public void Bypass_adds_the_companion_flag_and_nothing_else_does()
    {
        Assert.Contains("--dangerously-skip-permissions", ClaudeArgv.PermissionArgs("bypassPermissions"));
        foreach (var mode in new[] { "plan", "manual", "acceptEdits", "auto", "dontAsk" })
            Assert.DoesNotContain("--dangerously-skip-permissions", ClaudeArgv.PermissionArgs(mode));
    }

    [Theory]
    [InlineData("plan", "Bash,Read", "Read")]
    [InlineData("manual", "Bash,Read", "Read")]
    [InlineData("acceptEdits", "Bash,Read,Edit,Write", "Read,Edit,Write")]
    [InlineData("bypassPermissions", "Bash,Read,Edit,Write", "Read,Edit,Write")]
    public void Allowed_tools_per_mode(string mode, string plain, string live)
    {
        Assert.Equal(["--allowedTools", plain], ClaudeArgv.AllowedToolsArgs(mode, null, false));
        Assert.Equal(["--allowedTools", live], ClaudeArgv.AllowedToolsArgs(mode, null, true));
    }

    [Fact]
    public void Allowed_tools_list_replaces_default_and_rejects_commas()
    {
        Assert.Equal(["--allowedTools", "Read,Grep"], ClaudeArgv.AllowedToolsArgs("plan", ["Read", "Grep"], false));
        Assert.Empty(ClaudeArgv.AllowedToolsArgs("plan", [], false));
        Assert.Throws<ArgumentException>(() => ClaudeArgv.AllowedToolsArgs("plan", ["Bash(a,b)"], false));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    [InlineData("default")]
    [InlineData("Claude Code")]
    public void Model_placeholders_add_no_flag(string? model) => Assert.Empty(ClaudeArgv.ModelArgs(model));

    [Fact]
    public void Model_flag_and_flag_lookalike()
    {
        Assert.Equal(["--model", "opus"], ClaudeArgv.ModelArgs(" opus "));
        Assert.Throws<ArgumentException>(() => ClaudeArgv.ModelArgs("--yolo"));
    }

    [Fact]
    public void Token_file_denials_match_the_python_reference()
    {
        string[] expected =
        [
            "Read(//srv/x/.agent-cli-bridge/**)", "Edit(//srv/x/.agent-cli-bridge/**)", "Write(//srv/x/.agent-cli-bridge/**)",
            "Read(**/gateway-token)", "Bash(*gateway-token*)", "Read(**/gateway-owner-token)", "Bash(*gateway-owner-token*)",
            "Bash(*/srv/x/.agent-cli-bridge)", "Bash(*/srv/x/.agent-cli-bridge/*)", "Bash(*/srv/x/.agent-cli-bridge *)",
            "Bash(*.agent-cli-bridge/*)", "Bash(*/.agent-cli-bridge)", "Bash(*/.agent-cli-bridge *)",
        ];
        Assert.Equal(expected, ClaudeArgv.TokenFileDenials(Home));
    }

    [Fact]
    public void Token_file_denials_spell_a_home_relative_folder_every_way()
    {
        var user = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile).Replace('\\', '/').TrimEnd('/');
        var rules = ClaudeArgv.TokenFileDenials(user + "/.agent-cli-bridge");
        Assert.Contains("Bash(*$HOME/.agent-cli-bridge)", rules);
        Assert.Contains("Bash(*${HOME}/.agent-cli-bridge/*)", rules);
        Assert.Contains("Bash(*~/.agent-cli-bridge *)", rules);
    }

    [Fact]
    public void Default_argv_matches_the_python_reference_shape()
    {
        var argv = ClaudeArgv.Build(new ClaudeArgvRequest
        {
            Binary = "claude", Prompt = "-hi", SystemText = "SYS", ResumeId = "abc", Model = "opus",
            PermissionMode = "bypassPermissions", CliArgs = ["--x"], BridgeHome = Home, AllowSudo = true,
        });
        Assert.Equal(
            ["claude", "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
             "--model", "opus", "--resume", "abc", "--append-system-prompt", "SYS",
             "--permission-mode", "bypassPermissions", "--dangerously-skip-permissions",
             "--allowedTools", "Bash,Read,Edit,Write", "--disallowedTools"],
            argv.Take(18));
        Assert.Equal(["--x", "--", "-hi"], argv.TakeLast(3));
    }

    [Fact]
    public void Live_input_puts_the_prompt_on_stdin_and_omits_bash()
    {
        var argv = ClaudeArgv.Build(new ClaudeArgvRequest { Binary = "claude", Prompt = "hi", LiveInput = true, PermissionMode = "plan", BridgeHome = Home, AllowSudo = true });
        Assert.Equal(["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--replay-user-messages", "--permission-prompt-tool", "stdio"], argv.Take(11));
        Assert.Equal("Read", After(argv, "--allowedTools"));
        Assert.DoesNotContain("--", argv);
        Assert.DoesNotContain("hi", argv);
    }

    [Fact]
    public void Prompt_on_stdin_leaves_the_prompt_out()
    {
        var argv = ClaudeArgv.Build(new ClaudeArgvRequest { Binary = "claude", Prompt = "long", PromptOnStdin = true, BridgeHome = Home, AllowSudo = true });
        Assert.DoesNotContain("long", argv);
        Assert.DoesNotContain("--", argv);
    }

    [Fact]
    public void Resume_and_system_text_appear_only_when_given()
    {
        var argv = Build();
        Assert.DoesNotContain("--resume", argv);
        Assert.DoesNotContain("--append-system-prompt", argv);
    }

    [Theory]
    [Trait("Category", "Security")]
    [InlineData(false)]
    public void Sudo_off_disallows_sudo_pkexec_and_doas(bool allow)
    {
        var argv = ClaudeArgv.Build(new ClaudeArgvRequest { Binary = "claude", Prompt = "x", AllowSudo = allow, BridgeHome = Home });
        var i = argv.LastIndexOf("--disallowedTools");
        Assert.Equal("Bash(sudo:*),Bash(pkexec:*),Bash(doas:*)", argv[i + 1]);
        Assert.True(argv.IndexOf("--") > i);
    }

    [Fact]
    [Trait("Category", "Security")]
    public void Sudo_on_adds_no_sudo_rule_and_default_is_off()
    {
        var on = ClaudeArgv.Build(new ClaudeArgvRequest { Binary = "claude", Prompt = "x", AllowSudo = true, BridgeHome = Home });
        Assert.DoesNotContain(on, a => a.Contains("sudo:"));
        Assert.False(new ClaudeArgvRequest { Binary = "claude" }.AllowSudo);
        var off = ClaudeArgv.Build(new ClaudeArgvRequest { Binary = "claude", BridgeHome = Home });
        Assert.Contains(off, a => a.Contains("Bash(sudo:*)"));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void Token_files_are_always_denied()
    {
        var argv = Build();
        Assert.Contains("Read(**/gateway-owner-token)", After(argv, "--disallowedTools"));
    }

    [Theory]
    [InlineData("sonnet", "max", "max")]
    [InlineData("claude-opus-4-5", "xhigh", "high")]
    [InlineData("claude-opus-4-6", "xhigh", "high")]
    [InlineData("claude-opus-4-6", "max", "max")]
    [InlineData("claude-haiku-4-5", "high", null)]
    [InlineData("opus", "auto", null)]
    [InlineData("opus", "bogus", null)]
    public void Effort_is_clamped_per_model(string model, string effort, string? expected)
    {
        var args = Effort.Args("claude", effort, false, model);
        if (expected is null) Assert.Empty(args);
        else Assert.Equal(["--effort", expected], args);
    }

    [Fact]
    public void Ultracode_goes_through_settings_except_on_haiku_and_old_models()
    {
        Assert.Equal(["--settings", "{\"ultracode\":true}"], Effort.Args("claude", null, true, "opus"));
        Assert.Empty(Effort.Args("claude", null, true, "haiku"));
        Assert.Empty(Effort.Args("claude", null, true, "claude-3-5-sonnet-20241022"));
    }

    [Fact]
    public void Spec_lists_the_curated_models_with_sonnet_first()
    {
        Assert.Equal("sonnet", ClaudeSpec.Models[0]);
        Assert.Equal("claude", ClaudeSpec.Command);
    }
}
