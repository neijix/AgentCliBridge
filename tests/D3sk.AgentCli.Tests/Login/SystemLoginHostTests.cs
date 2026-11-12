using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

public sealed class SystemLoginHostTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("d3sk-login-").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task A_shell_script_stand_in_signs_in_over_real_pipes_and_is_ended_with_its_children()
    {
        if (OperatingSystem.IsWindows())
        {
            return; // the stand-in CLI is a shell script
        }
        var script = Path.Combine(_dir, "cursor-agent");
        File.WriteAllText(script, """
            #!/bin/sh
            if [ "$1" = login ]; then
              echo "browser=$NO_OPEN_BROWSER"
              echo "Open a browser and navigate to this link: https://cursor.com/loginDeepControl?uuid=1"
              sleep 30
            else
              echo "Not logged in"
            fi
            """);
        File.SetUnixFileMode(script, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        var ct = TestContext.Current.CancellationToken;
        var logins = new CliLogins(new SystemLoginHost());

        var started = await logins.StartAsync("cursor-agent", script, ct);
        Assert.Equal("https://cursor.com/loginDeepControl?uuid=1", started.Url);
        Assert.Contains("browser=1", started.Output);
        var status = await logins.StatusAsync("cursor-agent", script, ct);
        Assert.False(status.SignedIn);
        Assert.True(status.Running);
        await logins.StopAllAsync();
        Assert.False((await logins.StatusAsync("cursor-agent", script, ct)).Running);
    }
}
