using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Tests.ChildEnv;

public class ChildEnvironmentTests
{
    private static Dictionary<string, string> Host() => new() { ["PATH"] = "/usr/bin", ["HOME"] = "/home/x" };

    [Theory]
    [Trait("Category", "Security")]
    [InlineData(false)]
    [InlineData(true)]
    public void A_run_without_a_host_environment_is_refused(bool empty)
    {
        IReadOnlyDictionary<string, string>? none = empty ? new Dictionary<string, string>() : null;
        Assert.Throws<MissingChildEnvironmentException>(() => ChildEnvironment.Build(none));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void The_parent_environment_never_leaks_into_the_child()
    {
        Environment.SetEnvironmentVariable("D3SK_TEST_PARENT_SECRET", "s3cret");
        try
        {
            var env = ChildEnvironment.Build(Host(), isWindows: false);
            Assert.DoesNotContain("D3SK_TEST_PARENT_SECRET", env.Keys);
            Assert.Equal(2, env.Count);
        }
        finally
        {
            Environment.SetEnvironmentVariable("D3SK_TEST_PARENT_SECRET", null);
        }
    }

    [Fact]
    public void Transcript_killing_variables_are_dropped_when_asked()
    {
        var host = Host();
        host["CLAUDE_CODE_ENTRYPOINT"] = "cli";
        host["CLAUDECODE_X"] = "keep?";
        host["CLAUDE_CONFIG"] = "x";
        host["AI_AGENT"] = "1";
        host["AI_AGENT_NAME"] = "n";
        host["MY_AI_AGENT"] = "keep";
        var env = ChildEnvironment.Build(host, dropPrefixes: ChildEnvironment.TranscriptKillerPrefixes, isWindows: false);
        Assert.Equal(["CLAUDECODE_X", "HOME", "MY_AI_AGENT", "PATH"], env.Keys.Order(StringComparer.Ordinal));
        Assert.Contains("CLAUDE_CODE_ENTRYPOINT", ChildEnvironment.Build(host, isWindows: false).Keys);
    }

    [Fact]
    public void The_shim_folder_goes_first_on_PATH()
    {
        var env = ChildEnvironment.Build(Host(), shimFolder: "/shims", isWindows: false);
        Assert.Equal("/shims:/usr/bin", env["PATH"]);
    }

    [Fact]
    public void Windows_names_are_case_insensitive_and_the_Path_key_is_kept()
    {
        var host = new Dictionary<string, string> { ["Path"] = @"C:\a", ["claude_code_x"] = "1" };
        var env = ChildEnvironment.Build(host, @"C:\shims", ChildEnvironment.TranscriptKillerPrefixes, isWindows: true);
        Assert.Equal(@"C:\shims;C:\a", env["Path"]);
        Assert.Equal("C:\\shims;C:\\a", env["PATH"]);
        Assert.Single(env);
    }
}
