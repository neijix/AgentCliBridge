using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Tests.Specs.Claude;

public class ClaudeDiscoveryTests
{
    private static Func<string, bool> Only(params string[] present) => p => present.Contains(p);

    [Fact]
    public void Path_wins_over_the_local_bin()
    {
        var sep = Path.PathSeparator;
        var found = ClaudeDiscovery.Resolve($"/a{sep}/b", "/h", Only("/h/.local/bin/claude", Path.Combine("/b", "claude")));
        Assert.Equal(Path.Combine("/b", "claude"), found);
    }

    [Fact]
    public void Falls_back_to_the_local_bin()
    {
        Assert.Equal(Path.Combine("/h", ".local", "bin", "claude"),
            ClaudeDiscovery.Resolve("/a", "/h", Only(Path.Combine("/h", ".local", "bin", "claude"))));
    }

    [Fact]
    public void Tries_the_exe_twin()
    {
        var exe = Path.Combine("/a", "claude") + ".exe";
        Assert.Equal(exe, ClaudeDiscovery.Resolve("/a", "/h", Only(exe)));
    }

    [Fact]
    public void Nothing_found_is_null()
    {
        Assert.Null(ClaudeDiscovery.Resolve("/a", "/h", _ => false));
    }

    [Fact]
    public void A_non_executable_or_dangling_file_is_not_usable()
    {
        if (OperatingSystem.IsWindows()) return;
        var dir = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var plain = Path.Combine(dir, "claude");
            File.WriteAllText(plain, "x");
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            Assert.Null(ClaudeDiscovery.Resolve(dir, dir));
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Assert.Equal(plain, ClaudeDiscovery.Resolve(dir, dir));
            File.Delete(plain);
            File.CreateSymbolicLink(plain, Path.Combine(dir, "missing"));
            Assert.Null(ClaudeDiscovery.Resolve(dir, dir));
        }
        finally { Directory.Delete(dir, true); }
    }
}
