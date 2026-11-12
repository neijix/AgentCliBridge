using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Tests.ChildEnv;

public class WindowsLaunchTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("launch").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    private string Touch(params string[] parts)
    {
        var path = Path.Combine([_dir, .. parts]);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, "x");
        return path;
    }

    [Theory]
    [InlineData("a.cmd", true)]
    [InlineData("A.BAT", true)]
    [InlineData("a.cmd.", true)]
    [InlineData("a.cmd ", true)]
    [InlineData("a.exe", false)]
    public void IsLauncher_matches_the_cmd_exe_cases(string name, bool expected) =>
        Assert.Equal(expected, WindowsLaunch.IsLauncher(name));

    [Fact]
    public void Off_Windows_nothing_changes()
    {
        var plan = WindowsLaunch.DirectLaunch(["x.cmd", "a&b"], isWindows: false);
        Assert.Equal(["x.cmd", "a&b"], plan.Argv);
        Assert.Empty(plan.EnvOverlay);
    }

    [Fact]
    public void An_npm_shim_is_swapped_for_the_program_it_runs()
    {
        var exe = Touch("node_modules", "x", "tool.exe");
        var cmd = Touch("tool.cmd");
        File.WriteAllText(cmd, "@ECHO off\r\nSETLOCAL\r\n\"%dp0%\\node_modules\\x\\tool.exe\" %*\r\n");
        var plan = WindowsLaunch.DirectLaunch([cmd, "--p", "a & b \"q\""], isWindows: true);
        Assert.Equal([exe, "--p", "a & b \"q\""], plan.Argv);
    }

    [Fact]
    public void An_npm_shim_uses_the_node_beside_it_for_prog()
    {
        var node = Touch("node.exe");
        var js = Touch("node_modules", "g", "cli.js");
        var text = $"SET \"_prog=%dp0%\\node.exe\"\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & \"%_prog%\"  \"%dp0%\\node_modules\\g\\cli.js\" %*\r\n";
        Assert.Equal([node, js], WindowsLaunch.NpmShimArgv(text, _dir));
    }

    [Fact]
    public void A_missing_program_or_a_leftover_variable_gives_null()
    {
        Assert.Null(WindowsLaunch.NpmShimArgv("\"%dp0%\\nope.exe\" %*", _dir));
        Assert.Null(WindowsLaunch.NpmShimArgv("\"%OTHER%\\a.exe\" %*", _dir));
        Assert.Null(WindowsLaunch.NpmShimArgv("echo hi", _dir));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void A_launcher_it_cannot_see_through_is_refused_when_an_argument_is_special()
    {
        var cmd = Touch("odd.cmd");
        File.WriteAllText(cmd, "echo hello\r\n");
        Assert.Throws<UnsafeLauncherException>(() => WindowsLaunch.DirectLaunch([cmd, "a&calc"], isWindows: true));
        Assert.Throws<UnsafeLauncherException>(() => WindowsLaunch.DirectLaunch([cmd, "a\nb"], isWindows: true));
        Assert.Equal([cmd, "plain"], WindowsLaunch.DirectLaunch([cmd, "plain"], isWindows: true).Argv);
    }

    [Fact]
    public void Cursor_agent_picks_the_newest_complete_version_and_sets_its_env()
    {
        var cmd = Touch("agent.cmd");
        Touch("cursor-agent.ps1");
        Touch("versions", "2026.10.01-aaaaaaa", "node.exe");
        Touch("versions", "2026.10.01-aaaaaaa", "index.js");
        Touch("versions", "2026.10.01-14-05-09-bbbbbbb", "node.exe");
        Touch("versions", "2026.10.01-14-05-09-bbbbbbb", "index.js");
        Touch("versions", "2026.10.02-ccccccc", "node.exe"); // incomplete: no index.js
        var plan = WindowsLaunch.DirectLaunch([cmd, "-p", "hi"], new Dictionary<string, string> { ["LocalAppData"] = @"C:\L" }, isWindows: true);
        Assert.Equal(Path.Combine(_dir, "versions", "2026.10.01-14-05-09-bbbbbbb", "node.exe"), plan.Argv[0]);
        Assert.Equal(["-p", "hi"], plan.Argv.Skip(2));
        Assert.Equal("agent.cmd", plan.EnvOverlay["CURSOR_INVOKED_AS"]);
        Assert.StartsWith(@"C:\L", plan.EnvOverlay["NODE_COMPILE_CACHE"]);
    }

    [Fact]
    public void Command_line_length_follows_list2cmdline()
    {
        Assert.Equal(0, WindowsLaunch.CommandLineLength(["a"], isWindows: false));
        Assert.Equal("a \"b c\" \"\" x\\\"y".Length + 1, WindowsLaunch.CommandLineLength(["a", "b c", "", "x\"y"], isWindows: true));
        Assert.Equal("\"a b\\\\\"".Length + 1, WindowsLaunch.CommandLineLength(["a b\\"], isWindows: true));
    }

    [Fact]
    public void IsTooLong_checks_each_OS_limit()
    {
        var big = new string('x', WindowsLaunch.CommandLineLimit);
        Assert.True(WindowsLaunch.IsTooLong(["c", big], isWindows: true, isLinux: false));
        Assert.False(WindowsLaunch.IsTooLong(["c", big], isWindows: false, isLinux: false));
        Assert.True(WindowsLaunch.IsTooLong([new string('x', WindowsLaunch.LinuxArgLimit)], isWindows: false, isLinux: true));
        Assert.False(WindowsLaunch.IsTooLong([new string('x', WindowsLaunch.LinuxArgLimit - 1)], isWindows: false, isLinux: true));
    }
}
