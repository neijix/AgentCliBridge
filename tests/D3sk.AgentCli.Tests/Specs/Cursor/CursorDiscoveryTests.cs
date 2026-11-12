using D3sk.AgentCli.Specs.Cursor;

namespace D3sk.AgentCli.Tests.Specs.Cursor;

public class CursorDiscoveryTests
{
    [Fact]
    public void Each_alias_tries_the_path_then_the_local_bin_before_the_next_alias()
    {
        var local = Path.Combine("/h", ".local", "bin", "agent");
        var viaPath = Path.Combine("/a", "cursor-agent");
        Assert.Equal(local, CursorDiscovery.Resolve("/a", "/h", p => p == local || p == viaPath));
        Assert.Equal(viaPath, CursorDiscovery.Resolve("/a", "/h", p => p == viaPath));
        Assert.Equal(local, CursorDiscovery.Resolve("/a", "/h", p => p == local));
        Assert.Null(CursorDiscovery.Resolve("/a", "/h", _ => false));
    }

    [Fact]
    public void The_newest_versioned_install_is_the_last_resort()
    {
        var home = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var versions = Path.Combine(home, ".local", "share", "cursor-agent", "versions");
            foreach (var v in new[] { "2026.01.01", "2026.09.01" }) Directory.CreateDirectory(Path.Combine(versions, v));
            var all = Path.Combine(versions, "2026.09.01", "cursor-agent");
            Assert.Equal(all, CursorDiscovery.Resolve("", home, p => p == all || p == Path.Combine(versions, "2026.01.01", "agent")));
        }
        finally { Directory.Delete(home, true); }
    }

    [Theory]
    [Trait("Category", "Preserve")]
    [InlineData("C:\\Users\\me\\.grok\\bin\\agent.exe", true)]
    [InlineData("/Users/me/.grok/bin/agent", true)]
    [InlineData("/Users/me/.local/bin/agent", false)]
    [InlineData(null, false)]
    public void An_agent_inside_groks_bin_is_a_collision(string? path, bool collision) =>
        Assert.Equal(collision, CursorDiscovery.IsGrokCollision(path));
}
