using D3sk.AgentCli.Host;

namespace D3sk.AgentCli.Tests.Host;

public class AgentRegistryTests
{
    private static readonly string[] Commands = ["claude", "agent", "agy", "grok", "gemini", "copilot", "opencode"];

    private static DiscoveryOptions Machine(Dictionary<string, string?> binaries, Func<string, bool>? appExists = null) => new()
    {
        ResolveBinary = c => binaries.GetValueOrDefault(c),
        AppExists = appExists ?? (_ => false),
    };

    [Fact]
    [Trait("Category", "Preserve")]
    public void Lists_the_seven_CLIs_in_the_pickers_order()
    {
        Assert.Equal(Commands, AgentRegistry.All.Select(s => s.Command));
        Assert.Equal(["claude", "cursor", "antigravity", "grok", "gemini", "copilot", "opencode"], AgentRegistry.All.Select(s => s.Flavor));
        Assert.All(AgentRegistry.All, s => Assert.NotEmpty(s.Models));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Finds_a_spec_by_command_or_alias_and_maps_an_unknown_command_to_claude()
    {
        Assert.Equal("agent", AgentRegistry.Find("cursor-agent")?.Command);
        Assert.Equal("Cursor Agent", AgentRegistry.Find(" agent ")?.Name);
        Assert.Null(AgentRegistry.Find("nope"));
        Assert.Null(AgentRegistry.Find(null));
        Assert.Equal("cursor", AgentRegistry.FlavorFor("cursor-agent"));
        Assert.Equal("claude", AgentRegistry.FlavorFor("nope"));
    }

    [Fact]
    public void Resolves_each_command_with_its_own_discovery_rule()
    {
        var found = AgentRegistry.ResolveBinary("cursor-agent", pathEnv: "/bin", home: "/h", isUsable: p => p == "/bin/agent");
        Assert.Equal("/bin/agent", found);
        Assert.Equal("/bin/claude", AgentRegistry.ResolveBinary("claude", "/bin", "/h", null, p => p == "/bin/claude"));
        Assert.Equal("/bin/mytool", AgentRegistry.ResolveBinary("mytool", "/bin", "/h", null, p => p == "/bin/mytool"));
        Assert.Null(AgentRegistry.ResolveBinary("grok", "/bin", "/h", null, _ => false));
        Assert.Null(AgentRegistry.ResolveBinary("  ", "/bin", "/h", null, _ => true));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Discovery_keeps_registry_order_and_drops_what_is_not_installed()
    {
        var found = AgentDiscovery.Discover(Machine(new() { ["opencode"] = "/b/opencode", ["claude"] = "/b/claude" }));
        Assert.Equal(["claude", "opencode"], found.Select(a => a.Command));
        Assert.All(found, a => Assert.True(a.BinaryFound));
        Assert.All(found, a => Assert.Equal("", a.InstallHint));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void An_IDE_only_install_is_discovered_with_its_hint_but_never_offered()
    {
        var options = Machine([], p => p == "/Applications/Antigravity.app");
        var found = Assert.Single(AgentDiscovery.Discover(options));
        Assert.Equal("agy", found.Command);
        Assert.False(found.BinaryFound);
        Assert.Contains("Antigravity", found.InstallHint);
        Assert.Empty(AgentDiscovery.Available(options));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Disabled_agents_are_left_out_by_command_or_flavor()
    {
        var binaries = new Dictionary<string, string?> { ["claude"] = "/b/claude", ["agy"] = "/b/agy", ["grok"] = "/b/grok" };
        var options = Machine(binaries) with { Disabled = new HashSet<string> { "claude", "antigravity" } };
        Assert.Equal(["grok"], AgentDiscovery.Available(options).Select(a => a.Command));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void The_settings_model_list_wins_by_command_then_flavor_and_an_empty_list_means_curated()
    {
        var options = Machine(new() { ["claude"] = "/b/claude", ["agent"] = "/b/agent", ["grok"] = "/b/grok" }) with
        {
            ModelOverrides = new Dictionary<string, IReadOnlyList<string>>
            {
                ["claude"] = ["only-this"],
                ["cursor"] = ["by-flavor"],
                ["grok"] = [],
            },
        };
        var found = AgentDiscovery.Discover(options).ToDictionary(a => a.Command);
        Assert.Equal(["only-this"], found["claude"].Models);
        Assert.Equal(["by-flavor"], found["agent"].Models);
        Assert.Equal(AgentRegistry.Find("grok")!.Models, found["grok"].Models);
    }

    [Theory]
    [Trait("Category", "Security")]
    [InlineData("agent", "/home/u/.grok/bin/agent")]
    [InlineData("cursor-agent", "C:\\Users\\u\\.GROK\\bin\\cursor-agent.exe")]
    public void Cursors_name_resolving_to_Groks_binary_is_never_offered(string command, string path)
    {
        var options = Machine(new() { ["agent"] = path });
        var entry = Assert.Single(AgentDiscovery.Discover(options));
        Assert.True(entry.BinaryFound);
        Assert.True(AgentDiscovery.IsCursorGrokCollision(entry with { Command = command }));
        Assert.Empty(AgentDiscovery.Available(options));
    }

    [Fact]
    [Trait("Category", "Security")]
    public void Groks_own_entry_and_a_real_Cursor_binary_are_offered()
    {
        var options = Machine(new() { ["grok"] = "/home/u/.grok/bin/grok", ["agent"] = "/home/u/.local/bin/agent" });
        Assert.Equal(["agent", "grok"], AgentDiscovery.Available(options).Select(a => a.Command).Order());
        Assert.Contains("Grok CLI's own binary", AgentDiscovery.CollisionRefusal("Cursor Agent", "/x/.grok/bin/agent"));
    }
}
