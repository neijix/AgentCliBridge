using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Tests.ChildEnv;

public class ShimsTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("shims").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    [Fact]
    public void Posix_shim_content_and_quoting()
    {
        Assert.Equal("#!/bin/sh\nexec \"/v/bin/py\" -m mod.sub \"$@\"\n", Shims.PosixShim("/v/bin/py", "mod.sub"));
        Assert.Contains(@"\$HOME", Shims.PosixShim("/a/$HOME/py", "m"));
    }

    [Fact]
    public void Windows_files_are_a_cmd_and_a_git_bash_launcher()
    {
        var files = Shims.ShimFiles("tool", @"C:\v\100%\python.exe", "tool.cli", isWindows: true);
        Assert.Equal("@\"C:\\v\\100%%\\python.exe\" -m tool.cli %*\r\n", files["tool.cmd"]);
        Assert.Equal("#!/bin/sh\nexec \"C:/v/100%/python.exe\" -m tool.cli \"$@\"\n", files["tool"]);
    }

    [Theory]
    [InlineData("../x", "m", "/py")]
    [InlineData("n", "m;rm", "/py")]
    [InlineData("n", "m", "/p\"y")]
    [InlineData("n", "m", "")]
    public void Unsafe_input_is_refused(string name, string module, string python) =>
        Assert.Throws<ArgumentException>(() => Shims.EnsureShim(name, python, module, _dir, isWindows: false));

    [Fact]
    public void EnsureShim_writes_an_executable_launcher_and_keeps_it_when_unchanged()
    {
        Assert.Equal(_dir, Shims.EnsureShim("d3sk", "/v/py", "d3sk", _dir, isWindows: false));
        var path = Path.Combine(_dir, "d3sk");
        Assert.Equal(Shims.PosixShim("/v/py", "d3sk"), File.ReadAllText(path));
        if (!OperatingSystem.IsWindows())
        {
            Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute | UnixFileMode.GroupRead
                | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute, File.GetUnixFileMode(path));
        }
        var stamp = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(path, stamp);
        Shims.EnsureShim("d3sk", "/v/py", "d3sk", _dir, isWindows: false);
        Assert.Equal(stamp, File.GetLastWriteTimeUtc(path));
        Shims.EnsureShim("d3sk", "/v/py2", "d3sk", _dir, isWindows: false);
        Assert.Contains("/v/py2", File.ReadAllText(path));
        Assert.Empty(Directory.GetFiles(_dir, "*.tmp"));
    }

    [Fact]
    public void DefaultFolder_follows_the_pin_then_the_OS_cache_root()
    {
        Assert.Equal("/pin", Shims.DefaultFolder(n => n == Shims.ShimDirEnv ? " /pin " : null, false));
        Assert.Equal(Path.Combine("/c", "agent-cli-bridge", "bin"), Shims.DefaultFolder(n => n == "XDG_CACHE_HOME" ? "/c" : null, false));
        Assert.Equal(Path.Combine(@"C:\L", "agent-cli-bridge", "bin"), Shims.DefaultFolder(n => n == "LOCALAPPDATA" ? @"C:\L" : null, true));
    }

    [Fact]
    public void WithPath_moves_an_earlier_copy_to_the_front()
    {
        var env = Shims.WithPath(new Dictionary<string, string> { ["PATH"] = "/a:/s:/b" }, "/s", false);
        Assert.Equal("/s:/a:/b", env["PATH"]);
        Assert.Equal("/s", Shims.WithPath(new Dictionary<string, string>(), "/s", false)["PATH"]);
    }
}
