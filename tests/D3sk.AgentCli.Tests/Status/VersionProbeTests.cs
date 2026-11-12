using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Tests.Status;

[Trait("Preserve", "P38")]
public class VersionProbeTests
{
    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    private static VersionProbe Probe(List<string> events, bool isWindows, string? which, string stdout = "1.0.88", string stderr = "") =>
        new(
            (argv, _) =>
            {
                events.Add("run:" + string.Join(' ', argv));
                return Task.FromResult(new ProbeResult(0, stdout, stderr));
            },
            command => which,
            path =>
            {
                events.Add("clear:" + path);
                return false;
            },
            isWindows);

    [Fact]
    public async Task Windows_resolves_a_cmd_shim_to_its_full_path()
    {
        var events = new List<string>();
        var binary = @"C:\Users\me\AppData\Roaming\npm\copilot.cmd";
        var output = await Probe(events, isWindows: true, which: binary).RunAsync("copilot", "", Ct);
        Assert.Contains("1.0.88", output, StringComparison.Ordinal);
        Assert.Equal([$"clear:{binary}", $"run:{binary} --version"], events);
    }

    [Fact]
    public async Task Quarantine_is_cleared_before_the_cli_runs()
    {
        var events = new List<string>();
        await Probe(events, isWindows: false, which: "/opt/bin/claude").RunAsync("claude", "", Ct);
        Assert.Equal(["clear:/opt/bin/claude", "run:claude --version"], events);
    }

    [Fact]
    public async Task The_path_discovery_found_is_launched_with_no_second_lookup()
    {
        var events = new List<string>();
        await Probe(events, isWindows: true, which: "/elsewhere/claude").RunAsync("claude", "/found/claude", Ct);
        Assert.Equal(["clear:/found/claude", "run:/found/claude --version"], events);
    }

    [Fact]
    public async Task Stdout_then_stderr_are_the_text()
    {
        var output = await Probe([], false, null, stdout: "out", stderr: "err").RunAsync("x", "", Ct);
        Assert.Equal("out\nerr", output);
    }

    [Fact]
    public async Task A_program_that_cannot_start_throws_and_a_stuck_one_is_killed()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        await Assert.ThrowsAnyAsync<System.ComponentModel.Win32Exception>(
            () => ProbeProcess.RunAsync(["/nonexistent/cli-xyz", "--version"], TimeSpan.FromSeconds(5), Ct));
        var stuck = await Assert.ThrowsAsync<TimeoutException>(
            () => ProbeProcess.RunAsync(["/bin/sleep", "30"], TimeSpan.FromMilliseconds(200), Ct));
        Assert.Contains("timed out", stuck.Message, StringComparison.Ordinal);
        var done = await ProbeProcess.RunAsync(["/bin/echo", "2.1.0"], TimeSpan.FromSeconds(5), Ct);
        Assert.Equal("2.1.0", done.Stdout.Trim());
    }
}

[Trait("Preserve", "P38")]
public class MacQuarantineTests
{
    [Fact]
    public void Only_the_quarantine_attribute_is_stripped()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        using var dir = new TempDir();
        var binary = dir.File("claude");
        var calls = new List<string>();
        Assert.True(MacQuarantine.Clear(binary, isMac: true, xattr: args => { calls.Add(string.Join(' ', args)); return 0; }));
        Assert.Equal([$"-p com.apple.quarantine {binary}", $"-d com.apple.quarantine {binary}"], calls);
    }

    [Fact]
    public void A_clean_binary_is_left_alone()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        using var dir = new TempDir();
        var calls = new List<string>();
        Assert.False(MacQuarantine.Clear(dir.File("claude"), isMac: true, xattr: args => { calls.Add(args[0]); return 1; }));
        Assert.Equal(["-p"], calls);
    }

    [Fact]
    public void It_is_a_no_op_off_macos_and_for_a_missing_file()
    {
        using var dir = new TempDir();
        var calls = 0;
        Assert.False(MacQuarantine.Clear(dir.File("claude"), isMac: false, xattr: _ => ++calls));
        Assert.False(MacQuarantine.Clear("", isMac: true, xattr: _ => ++calls));
        Assert.False(MacQuarantine.Clear(Path.Combine(Path.GetTempPath(), "no-such-cli-binary"), isMac: true, xattr: _ => ++calls));
        Assert.Equal(0, calls);
    }
}
