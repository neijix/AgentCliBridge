using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

public sealed class CopilotSignInTests : IDisposable
{
    private readonly string _home = Directory.CreateTempSubdirectory("d3sk-copilot-").FullName;
    private readonly FakeLoginHost _host = new();

    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    public CopilotSignInTests() => _host.Env["PATH"] = ""; // never the machine's own gh

    public void Dispose() => Directory.Delete(_home, recursive: true);

    private Task<bool?> Check() => CopilotSignIn.IsSignedInAsync(_host, _home, TimeSpan.FromSeconds(1), Ct);

    private void Config(string text)
    {
        Directory.CreateDirectory(Path.Combine(_home, ".copilot"));
        File.WriteAllText(Path.Combine(_home, ".copilot", "config.json"), text);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task A_token_in_the_environment_is_a_sign_in()
    {
        _host.Env["GH_TOKEN"] = "x";
        Assert.True(await Check());
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task The_config_s_logged_in_users_decide_and_comment_lines_are_skipped()
    {
        Assert.False(await Check()); // never launched
        Config("// User settings\n{\"logged_in_users\": [{\"host\": \"github.com\"}]}");
        Assert.True(await Check());
        Config("// User settings\n{\"logged_in_users\": []}");
        Assert.False(await Check());
        Config("{not json");
        Assert.Null(await Check());
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task The_github_cli_s_login_is_the_fallback_and_its_token_is_never_asked()
    {
        var bin = Path.Combine(_home, "bin");
        Directory.CreateDirectory(bin);
        var gh = Path.Combine(bin, "gh");
        File.WriteAllText(gh, "#!/bin/sh\n");
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(gh, UnixFileMode.UserRead | UnixFileMode.UserExecute | UnixFileMode.UserWrite);
        }
        _host.Env["PATH"] = bin;
        var asked = new List<string>();
        _host.Answer = argv =>
        {
            asked.AddRange(argv.Skip(1));
            return new LoginCommandResult(0, "", "");
        };
        Assert.True(await Check());
        Assert.Equal(["auth", "status", "--hostname", "github.com"], asked);
        _host.Answer = _ => new LoginCommandResult(1, "", "");
        Config("{\"logged_in_users\": []}");
        Assert.False(await Check());
    }
}
