using D3sk.AgentCli.Specs.Agy;

namespace D3sk.AgentCli.Tests.Specs.Agy;

public class AgyDiscoveryTests
{
    private static Func<string, bool> Only(params string[] present) => p => present.Contains(p);

    [Fact]
    public void Path_wins_over_the_vendor_folders()
    {
        var onPath = Path.Combine("/b", "agy");
        Assert.Equal(onPath, AgyDiscovery.Resolve("/b", "/h", Only(onPath, Path.Combine("/h", ".antigravity", "Antigravity", "bin", "agy"))));
    }

    [Fact]
    public void Finds_the_official_windows_layout_exe()
    {
        var exe = Path.Combine("/local", "agy", "bin", "agy") + ".exe";
        Assert.Equal(exe, AgyDiscovery.Resolve("/a", "/h", Only(exe), "/local"));
    }

    [Fact]
    public void Finds_the_exe_next_to_the_unix_layout()
    {
        var exe = Path.Combine("/h", ".antigravity", "Antigravity", "bin", "agy") + ".exe";
        Assert.Equal(exe, AgyDiscovery.Resolve("/a", "/h", Only(exe), "/local"));
    }

    [Fact]
    public void Local_bin_comes_before_the_vendor_folders()
    {
        var local = Path.Combine("/h", ".local", "bin", "agy");
        Assert.Equal(local, AgyDiscovery.Resolve("/a", "/h", Only(Path.Combine("/h", ".antigravity", "Antigravity", "bin", "agy"), local), "/local"));
    }

    [Fact]
    public void Local_app_data_defaults_under_home()
    {
        var path = Path.Combine("/h", "AppData", "Local", "agy", "bin", "agy");
        Assert.Equal(path, AgyDiscovery.Resolve("/a", "/h", Only(path), ""));
    }

    [Fact]
    public void Nothing_found_is_null()
    {
        Assert.Null(AgyDiscovery.Resolve("/a", "/h", _ => false, "/local"));
    }

    [Fact]
    public void A_non_executable_or_dangling_file_is_not_usable()
    {
        if (OperatingSystem.IsWindows()) return;
        var dir = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var plain = Path.Combine(dir, "agy");
            File.WriteAllText(plain, "x");
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            Assert.Null(AgyDiscovery.Resolve(dir, dir, null, dir));
            File.SetUnixFileMode(plain, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Assert.Equal(plain, AgyDiscovery.Resolve(dir, dir, null, dir));
            File.Delete(plain);
            File.CreateSymbolicLink(plain, Path.Combine(dir, "missing"));
            Assert.Null(AgyDiscovery.Resolve(dir, dir, null, dir));
        }
        finally { Directory.Delete(dir, true); }
    }
}
