using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

public class UpdatePlansTests
{
    private static string Tool(string name) => name;

    [Fact]
    [Trait("Preserve", "P38")]
    public void Update_upgrades_the_copy_the_node_runs_the_way_it_was_installed()
    {
        var cask = UpdatePlans.Update("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code@latest/2.1.280/claude");
        Assert.Equal(["/opt/homebrew/bin/brew", "upgrade", "--cask", "claude-code@latest"], cask.Argv);
        Assert.Empty(cask.Then);
        var formula = UpdatePlans.Update("opencode", "/opt/homebrew/bin/opencode", "/opt/homebrew/Cellar/opencode/1.18.30_2/bin/opencode");
        Assert.Equal(["/opt/homebrew/bin/brew", "upgrade", "opencode"], formula.Argv);
        var scoped = UpdatePlans.Update("gemini", "/opt/homebrew/bin/gemini", "/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js");
        Assert.Equal(["/opt/homebrew/bin/npm", "install", "-g", "@google/gemini-cli@latest"], scoped.Argv);
        const string shim = @"C:\Users\me\AppData\Roaming\npm\copilot.cmd";
        var windows = UpdatePlans.Update("copilot", shim, shim, isWindows: true, tool: Tool);
        Assert.Equal(["npm.cmd", "install", "-g", "--prefix", @"C:\Users\me\AppData\Roaming\npm", "@github/copilot@latest"], windows.Argv);
        var cursor = UpdatePlans.Update("agent", "/Users/me/.local/bin/agent", "/Users/me/.local/share/cursor-agent/versions/2026.09.18/cursor-agent");
        Assert.Equal(["/Users/me/.local/bin/agent", "update"], cursor.Argv);
        Assert.Equal(["update"], UpdatePlans.Update("agy", "/Users/me/.local/bin/agy", "/Users/me/.local/bin/agy").Argv.Skip(1));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void A_native_Windows_Grok_uses_its_own_updater_not_a_second_npm_install()
    {
        const string binary = @"C:\Users\me\.grok\bin\grok.exe";
        var plan = UpdatePlans.Update("grok", binary, binary, isWindows: true, tool: Tool);
        Assert.Equal([binary, "update"], plan.Argv);
        Assert.Equal("its own updater", plan.How);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void A_WinGet_Copilot_updates_only_the_recognized_package()
    {
        const string binary = @"C:\Users\me\AppData\Local\Microsoft\WinGet\Links\copilot.exe";
        const string resolved = @"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\copilot.exe";
        var plan = UpdatePlans.Update("copilot", binary, resolved, isWindows: true, tool: Tool);
        Assert.Equal(
            ["winget", "upgrade", "--id", "GitHub.Copilot", "--exact", "--source", "winget", "--silent", "--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements"],
            plan.Argv);
        Assert.Equal("WinGet", plan.How);
        foreach (var unknown in new[] { @"C:\custom\copilot.exe", resolved.Replace("GitHub.Copilot_", "Other.Copilot_"), resolved.Replace("WinGet", "OtherManager") })
        {
            Assert.Empty(UpdatePlans.Update("copilot", binary, unknown, isWindows: true, tool: Tool).Argv);
        }
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void The_stable_Claude_cask_is_switched_to_its_latest_twin_download_first()
    {
        var plan = UpdatePlans.Update("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code/2.1.267/claude");
        Assert.Equal(["/opt/homebrew/bin/brew", "fetch", "--cask", "claude-code@latest"], plan.Argv);
        Assert.Equal(
            [["/opt/homebrew/bin/brew", "uninstall", "--cask", "claude-code"], ["/opt/homebrew/bin/brew", "install", "--cask", "claude-code@latest"]],
            plan.Then.Select(t => t.ToArray()));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void A_CLI_with_no_known_updater_gets_a_hint_not_a_guess()
    {
        var plan = UpdatePlans.Update("gemini", "/usr/local/bin/gemini", "/usr/local/bin/gemini");
        Assert.False(plan.Runnable);
        Assert.Equal("npm install -g @google/gemini-cli@latest", plan.Hint);
        Assert.False(UpdatePlans.Update("mystery", "/usr/bin/mystery", "/usr/bin/mystery").Runnable);
    }

    [Theory]
    [Trait("Preserve", "P38")]
    [InlineData("--registry=evil")]
    [InlineData("Upper")]
    [InlineData("..")]
    public void A_package_folder_that_is_not_a_package_name_is_not_installed(string folder)
    {
        Assert.False(UpdatePlans.Update("gemini", "/x/bin/gemini", $"/x/lib/node_modules/{folder}/bin.js").Runnable);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void Uninstall_removes_the_copy_the_node_runs_the_way_it_was_installed()
    {
        Assert.Equal(["/opt/homebrew/bin/brew", "uninstall", "--cask", "claude-code@latest"],
            UpdatePlans.Uninstall("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code@latest/2.1.280/claude").Argv);
        Assert.Equal(["/opt/homebrew/bin/brew", "uninstall", "opencode"],
            UpdatePlans.Uninstall("opencode", "/opt/homebrew/bin/opencode", "/opt/homebrew/Cellar/opencode/2.0.20/bin/opencode").Argv);
        Assert.Equal(["/opt/homebrew/bin/npm", "uninstall", "-g", "@xai-official/grok"],
            UpdatePlans.Uninstall("grok", "/opt/homebrew/bin/grok", "/opt/homebrew/lib/node_modules/@xai-official/grok/bin/grok-native").Argv);
        const string shim = @"C:\Users\me\AppData\Roaming\npm\copilot.cmd";
        Assert.Equal(["npm.cmd", "uninstall", "-g", "--prefix", @"C:\Users\me\AppData\Roaming\npm", "@github/copilot"],
            UpdatePlans.Uninstall("copilot", shim, shim, isWindows: true, tool: Tool).Argv);
        // Something the host cannot tell how it was installed is a hint, never a guess at what to delete.
        var unknown = UpdatePlans.Uninstall("agy", "/Users/me/.local/bin/agy", "/Users/me/.local/bin/agy", home: Path.GetTempPath());
        Assert.False(unknown.Runnable);
        Assert.Contains("/Users/me/.local/bin/agy", unknown.Hint);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void A_WinGet_package_is_removed_by_its_own_id()
    {
        var agy = UpdatePlans.Uninstall("agy",
            @"C:\Users\me\AppData\Local\Microsoft\WinGet\Links\agy.exe",
            @"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\Google.AntigravityCLI_Microsoft.Winget.Source_8wekyb3d8bbwe\agy.EXE",
            isWindows: true, tool: Tool);
        Assert.Equal(["winget", "uninstall", "--id", "Google.AntigravityCLI"], agy.Argv.Take(4));
        Assert.Equal("WinGet", agy.How);
        const string other = @"C:\Users\me\AppData\Local\Microsoft\WinGet\Packages\GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe\agy.exe";
        Assert.False(UpdatePlans.Uninstall("agy", other, other, isWindows: true, tool: Tool).Runnable);
    }
}
