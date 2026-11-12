using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

public class InstallPlansTests
{
    private static readonly Func<string, string?> NoneOnPath = _ => null;
    private static readonly Func<IEnumerable<string>, string> NothingFound = _ => "";
    private const string Powershell = @"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe";
    private const string Winget = @"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe";

    [Fact]
    [Trait("Preserve", "P38")]
    [Trait("Security", "B18")]
    public void A_script_install_is_a_download_then_a_file_run_never_a_pipe_into_a_shell()
    {
        foreach (var command in new[] { "claude", "agent", "agy" })
        {
            var plan = InstallPlans.For(command, home: "/h", which: NoneOnPath, find: NothingFound);
            Assert.Empty(plan.Argv);
            Assert.StartsWith("https://", plan.Script!.Url);
            Assert.Equal(["/bin/bash"], plan.Script.Interpreter);
            Assert.DoesNotContain("|", plan.Manual);
            Assert.DoesNotContain("-c", plan.Script.Interpreter);
        }
        Assert.Equal("https://claude.ai/install.sh", InstallPlans.For("claude", home: "/h", which: NoneOnPath, find: NothingFound).Script!.Url);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void Install_uses_the_npm_it_finds_then_Homebrew_Node_and_never_a_name_it_does_not_know()
    {
        var npm = InstallPlans.For("grok", home: "/h", which: n => n == "npm" ? "/usr/local/bin/npm" : null, find: NothingFound);
        Assert.Equal(["/usr/local/bin/npm", "install", "-g", "@xai-official/grok"], npm.Argv);
        Assert.Equal("npm", npm.How);
        var brew = InstallPlans.For("gemini", home: "/h", which: NoneOnPath, find: paths => paths.Contains("/opt/homebrew/bin/brew") && !paths.Contains("/opt/homebrew/bin/npm") ? "/opt/homebrew/bin/brew" : "");
        Assert.Equal(["/opt/homebrew/bin/brew", "install", "node"], brew.Argv);
        Assert.Equal([["/opt/homebrew/bin/npm", "install", "-g", "@google/gemini-cli"]], brew.Then.Select(t => t.ToArray()));
        var bare = InstallPlans.For("copilot", home: "/h", which: NoneOnPath, find: NothingFound);
        Assert.False(bare.Runnable);
        Assert.Contains("npm install -g @github/copilot", bare.Hint);
        Assert.False(InstallPlans.For("rm -rf /", home: "/h", which: NoneOnPath, find: NothingFound).Runnable);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void Windows_uses_WinGet_for_Antigravity_and_a_saved_PowerShell_file_for_the_others()
    {
        Func<string, string?> onPath = n => n;
        var agy = InstallPlans.For("agy", isWindows: true, which: onPath, find: NothingFound);
        Assert.Equal(["winget", "install", "-e", "--id", "Google.AntigravityCLI"], agy.Argv.Take(5));
        var claude = InstallPlans.For("claude", isWindows: true, which: onPath, find: NothingFound);
        Assert.Equal("powershell", claude.Script!.Interpreter[0]);
        Assert.Equal("-File", claude.Script.Interpreter[^1]);
        Assert.Equal("install.ps1", claude.Script.FileName);
        Assert.DoesNotContain("iex", claude.Manual);
        Assert.DoesNotContain("-Command", claude.Script.Interpreter);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void Windows_tools_are_found_by_full_path_off_a_background_PATH()
    {
        // A fake environment: setting the process's own would race other tests that read LOCALAPPDATA.
        Func<string, string?> env = name => name switch
        {
            "SystemRoot" => @"C:\Windows",
            "LOCALAPPDATA" => @"C:\Users\me\AppData\Local",
            _ => null,
        };
        Func<IEnumerable<string>, string> both = paths => paths.FirstOrDefault(p => p is Powershell or Winget) ?? "";
        var cursor = InstallPlans.For("agent", isWindows: true, which: NoneOnPath, find: both, env: env);
        Assert.Equal(Powershell, cursor.Script!.Interpreter[0]);
        Assert.Equal("https://cursor.com/install?win32=true", cursor.Script.Url);
        var agy = InstallPlans.For("agy", isWindows: true, which: NoneOnPath, find: both, env: env);
        Assert.Equal([Winget, "install", "-e", "--id", "Google.AntigravityCLI"], agy.Argv.Take(5));
        // No WinGet at all: Google's own PowerShell script, saved and run from a file.
        var fallback = InstallPlans.For("agy", isWindows: true, which: NoneOnPath, find: p => p.Contains(Powershell) ? Powershell : "", env: env);
        Assert.Equal("https://antigravity.google/cli/install.ps1", fallback.Script!.Url);
        // Nothing to run with: a hint the owner can follow, never a bare name.
        var nothing = InstallPlans.For("agent", isWindows: true, which: NoneOnPath, find: NothingFound, env: env);
        Assert.False(nothing.Runnable);
        Assert.Contains("cursor.com/install", nothing.Hint);
    }
}
