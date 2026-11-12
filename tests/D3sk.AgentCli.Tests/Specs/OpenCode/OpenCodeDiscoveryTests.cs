using D3sk.AgentCli.Specs.OpenCode;

namespace D3sk.AgentCli.Tests.Specs.OpenCode;

public class OpenCodeDiscoveryTests
{
    private static Func<string, bool> Only(params string[] present) => p => present.Contains(p);

    [Fact]
    public void Path_wins_over_the_local_bin()
    {
        var sep = Path.PathSeparator;
        var onPath = Path.Combine("/b", "opencode");
        Assert.Equal(onPath, OpenCodeDiscovery.Resolve($"/a{sep}/b", "/h", Only(Path.Combine("/h", ".local", "bin", "opencode"), onPath)));
    }

    [Fact]
    public void Falls_back_to_the_local_bin_and_the_exe_twin()
    {
        var local = Path.Combine("/h", ".local", "bin", "opencode");
        Assert.Equal(local, OpenCodeDiscovery.Resolve("/a", "/h", Only(local)));
        Assert.Equal(Path.Combine("/a", "opencode") + ".exe", OpenCodeDiscovery.Resolve("/a", "/h", Only(Path.Combine("/a", "opencode") + ".exe")));
        Assert.Null(OpenCodeDiscovery.Resolve("/a", "/h", _ => false));
    }

    [Fact]
    public void A_non_executable_file_is_not_usable()
    {
        if (OperatingSystem.IsWindows()) return;
        var dir = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var plain = Path.Combine(dir, "opencode");
            File.WriteAllText(plain, "x");
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            Assert.Null(OpenCodeDiscovery.Resolve(dir, dir));
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Assert.Equal(plain, OpenCodeDiscovery.Resolve(dir, dir));
        }
        finally { Directory.Delete(dir, true); }
    }
}
