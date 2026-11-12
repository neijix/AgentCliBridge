using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

public sealed class NativeInstallsTests : IDisposable
{
    private readonly string _home = Directory.CreateTempSubdirectory("native-home").FullName;

    public void Dispose() => Directory.Delete(_home, recursive: true);

    private string Cursor(out string bin, out string share)
    {
        share = Path.Combine(_home, ".local", "share", "cursor-agent");
        var versions = Path.Combine(share, "versions", "2026.10.01");
        Directory.CreateDirectory(versions);
        var real = Path.Combine(versions, "cursor-agent");
        File.WriteAllText(real, "bin");
        bin = Path.Combine(_home, ".local", "bin");
        Directory.CreateDirectory(bin);
        File.CreateSymbolicLink(Path.Combine(bin, "agent"), real);
        File.CreateSymbolicLink(Path.Combine(bin, "cursor-agent"), real);
        return real;
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void A_native_install_removes_only_its_own_folder_and_links()
    {
        var real = Cursor(out var bin, out var share);
        var other = Path.Combine(_home, "elsewhere");
        File.WriteAllText(other, "x");
        File.CreateSymbolicLink(Path.Combine(bin, "claude"), other);  // not Cursor's: stays
        var plan = UpdatePlans.Uninstall("agent", Path.Combine(bin, "agent"), real, home: _home);
        Assert.Equal(share, plan.Remove!.Dir);
        Assert.Equal([Path.Combine(bin, "agent"), Path.Combine(bin, "cursor-agent")], plan.Remove.Links);
        var outcome = NativeInstalls.Remove(plan.Remove);
        Assert.True(outcome.Ok);
        Assert.Contains("Removed", outcome.Output);
        Assert.False(Directory.Exists(share));
        Assert.Null(new FileInfo(Path.Combine(bin, "agent")).LinkTarget);
        Assert.False(File.Exists(Path.Combine(bin, "agent")));
        Assert.NotNull(new FileInfo(Path.Combine(bin, "claude")).LinkTarget);
        Assert.True(File.Exists(other));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void Groks_own_installer_removes_only_its_bin_folder()
    {
        var grokHome = Path.Combine(_home, ".grok");
        var bin = Path.Combine(grokHome, "bin");
        Directory.CreateDirectory(bin);
        File.WriteAllText(Path.Combine(bin, "grok"), "bin");
        File.WriteAllText(Path.Combine(grokHome, "auth.json"), "{}");  // the sign-in stays
        var binary = Path.Combine(bin, "grok");
        var plan = UpdatePlans.Uninstall("grok", binary, binary, home: _home);
        Assert.Equal(new RemoveTarget(bin, []).Dir, plan.Remove!.Dir);
        Assert.True(NativeInstalls.Remove(plan.Remove).Ok);
        Assert.False(Directory.Exists(bin));
        Assert.True(File.Exists(Path.Combine(grokHome, "auth.json")));
        Directory.CreateDirectory(bin);
        // A grok elsewhere, or another CLI inside ~/.grok/bin, is never removed as Grok's folder.
        Assert.Null(UpdatePlans.Uninstall("grok", "/usr/local/bin/grok", "/usr/local/bin/grok", home: _home).Remove);
        Assert.Null(UpdatePlans.Uninstall("agy", Path.Combine(bin, "agy"), Path.Combine(bin, "agy"), home: _home).Remove);
    }

    [Fact]
    [Trait("Security", "native-remove")]
    public void A_binary_outside_the_native_folder_is_never_removed_as_native()
    {
        Directory.CreateDirectory(Path.Combine(_home, ".local", "share", "claude"));
        var plan = UpdatePlans.Uninstall("claude", "/usr/local/bin/claude", "/usr/local/lib/claude", home: _home);
        Assert.Null(plan.Remove);
        Assert.False(plan.Runnable);
    }

    [Fact]
    [Trait("Security", "native-remove")]
    public void A_symlinked_install_folder_is_never_followed_or_deleted()
    {
        var victim = Path.Combine(_home, "victim");
        Directory.CreateDirectory(victim);
        File.WriteAllText(Path.Combine(victim, "keep"), "x");
        var linked = Path.Combine(_home, "linked");
        Directory.CreateSymbolicLink(linked, victim);
        Assert.True(NativeInstalls.Remove(new RemoveTarget(linked, [])).Ok);
        Assert.True(File.Exists(Path.Combine(victim, "keep")));
        // And such a folder is not planned as a native install in the first place.
        var share = Path.Combine(_home, ".local", "share");
        Directory.CreateDirectory(share);
        Directory.CreateSymbolicLink(Path.Combine(share, "claude"), victim);
        var binary = Path.Combine(share, "claude", "keep");
        Assert.Null(NativeInstalls.SelfInstalled("claude", Path.Combine(_home, ".local", "bin", "claude"), binary, _home));
    }
}
