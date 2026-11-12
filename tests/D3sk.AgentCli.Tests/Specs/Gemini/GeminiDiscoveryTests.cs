using D3sk.AgentCli.Specs.Gemini;

namespace D3sk.AgentCli.Tests.Specs.Gemini;

public class GeminiDiscoveryTests
{
    private static Func<string, bool> Only(params string[] present) => p => present.Contains(p);

    [Fact]
    public void Path_wins_over_the_local_bin()
    {
        var sep = Path.PathSeparator;
        var found = GeminiDiscovery.Resolve($"/a{sep}/b", "/h", Only(Path.Combine("/h", ".local", "bin", "gemini"), Path.Combine("/b", "gemini")));
        Assert.Equal(Path.Combine("/b", "gemini"), found);
    }

    [Fact]
    public void Falls_back_to_the_local_bin_and_tries_the_exe_twin()
    {
        var local = Path.Combine("/h", ".local", "bin", "gemini");
        Assert.Equal(local, GeminiDiscovery.Resolve("/a", "/h", Only(local)));
        var exe = Path.Combine("/a", "gemini") + ".exe";
        Assert.Equal(exe, GeminiDiscovery.Resolve("/a", "/h", Only(exe)));
        Assert.Null(GeminiDiscovery.Resolve("/a", "/h", _ => false));
    }
}
