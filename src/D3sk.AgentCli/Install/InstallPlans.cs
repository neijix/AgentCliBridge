using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Install;

/// <summary>
/// How to install a missing CLI with its vendor's documented installer: Claude Code, Cursor and
/// Antigravity from their install scripts (WinGet for Antigravity on Windows), the npm-published
/// ones with the npm on this machine. A script is downloaded, checked and run from a file — the
/// documented <c>curl | bash</c> is never run as such. The strings are fixed here, never built from a request.
/// </summary>
public static class InstallPlans
{
    private static readonly Dictionary<string, string> Scripts = new(StringComparer.Ordinal)
    {
        ["claude"] = "https://claude.ai/install.sh",
        ["agent"] = "https://cursor.com/install",
        ["agy"] = "https://antigravity.google/cli/install.sh",
    };

    private static readonly Dictionary<string, string> WindowsScripts = new(StringComparer.Ordinal)
    {
        ["claude"] = "https://claude.ai/install.ps1",
        ["agent"] = "https://cursor.com/install?win32=true",
    };

    private static readonly Dictionary<string, string> WingetInstalls = new(StringComparer.Ordinal) { ["agy"] = "Google.AntigravityCLI" };

    // Google's script, used only when WinGet cannot be found (it goes through the WinINET proxy,
    // which a corporate laptop may refuse with a 407 that WinGet does not hit).
    private static readonly Dictionary<string, string> WindowsFallbackScripts = new(StringComparer.Ordinal)
    {
        ["agy"] = "https://antigravity.google/cli/install.ps1",
    };

    private static readonly string[] NpmPlaces = ["/opt/homebrew/bin/npm", "/usr/local/bin/npm"];
    private static readonly string[] BrewPlaces = ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"];

    /// <summary>The CLIs installed through npm.</summary>
    public static IReadOnlyList<string> NpmCommands { get; } = ["gemini", "copilot", "grok", "opencode"];

    /// <summary>
    /// The plan for a missing <paramref name="command"/>; empty with a hint when none is known.
    /// <paramref name="env"/> reads the Windows folders (<c>SystemRoot</c>, <c>LOCALAPPDATA</c>); the process environment by default.
    /// </summary>
    public static CliPlan For(
        string command,
        bool isWindows = false,
        string? home = null,
        Func<string, string?>? which = null,
        Func<IEnumerable<string>, string>? find = null,
        Func<string, string?>? env = null)
    {
        which ??= n => CliTools.Which(n);
        find ??= CliTools.FirstExecutable;
        return isWindows ? ForWindows(command, which, find, env) : ForUnix(command, home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), which, find);
    }

    private static CliPlan ForWindows(string command, Func<string, string?> which, Func<IEnumerable<string>, string> find, Func<string, string?>? env)
    {
        var script = WindowsScripts.GetValueOrDefault(command);
        if (WingetInstalls.TryGetValue(command, out var packageId))
        {
            var winget = which("winget") ?? find(CliTools.WindowsPlaces("LOCALAPPDATA", @"Microsoft\WindowsApps\winget.exe", env));
            if (!string.IsNullOrEmpty(winget))
            {
                return new CliPlan
                {
                    Argv =
                    [
                        winget, "install", "-e", "--id", packageId, "--source", "winget",
                        "--silent", "--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements",
                    ],
                    How = "WinGet",
                    Manual = $"winget install -e --id {packageId}",
                };
            }
            script = WindowsFallbackScripts.GetValueOrDefault(command);
            if (script is null)
            {
                return new CliPlan { Hint = $"install App Installer (WinGet), then: winget install -e --id {packageId}" };
            }
        }
        if (script is not null)
        {
            var powershell = which("powershell") ?? find(CliTools.WindowsPlaces("SystemRoot", @"System32\WindowsPowerShell\v1.0\powershell.exe", env));
            if (string.IsNullOrEmpty(powershell))
            {
                return new CliPlan { Hint = $"in a PowerShell window, save {script} to a file, read it, then run it" };
            }
            return Script(script, "install.ps1", [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]);
        }
        if (!UpdatePlans.NpmPackages.TryGetValue(command, out var package) || !NpmCommands.Contains(command))
        {
            return new CliPlan { Hint = $"no installer is known for '{command}'" };
        }
        var npm = which("npm.cmd") ?? which("npm") ?? "";
        return npm.Length == 0
            ? new CliPlan { Hint = $"install Node.js (https://nodejs.org), then: npm install -g {package}" }
            : new CliPlan { Argv = [npm, "install", "-g", package], How = "npm" };
    }

    private static CliPlan ForUnix(string command, string home, Func<string, string?> which, Func<IEnumerable<string>, string> find)
    {
        if (Scripts.TryGetValue(command, out var url))
        {
            return Script(url, "install.sh", ["/bin/bash"]);
        }
        if (!NpmCommands.Contains(command))
        {
            return new CliPlan { Hint = $"no installer is known for '{command}'" };
        }
        var package = UpdatePlans.NpmPackages[command];
        var npm = which("npm");
        if (string.IsNullOrEmpty(npm))
        {
            npm = find([.. NpmPlaces, Path.Combine(home, ".local", "bin", "npm")]);
        }
        if (npm.Length > 0)
        {
            return new CliPlan { Argv = [npm, "install", "-g", package], How = "npm" };
        }
        var brew = which("brew");
        if (string.IsNullOrEmpty(brew))
        {
            brew = find(BrewPlaces);
        }
        if (brew.Length > 0)
        {
            var brewNpm = Path.Combine(Path.GetDirectoryName(brew) ?? "", "npm");
            return new CliPlan
            {
                Argv = [brew, "install", "node"],
                Then = [[brewNpm, "install", "-g", package]],
                How = "Homebrew Node.js, then npm",
            };
        }
        return new CliPlan { Hint = $"install Node.js (https://nodejs.org), then: npm install -g {package}" };
    }

    private static CliPlan Script(string url, string fileName, string[] interpreter) => new()
    {
        Script = new ScriptSource(url, fileName, interpreter),
        How = "its install script",
        Manual = $"download {url}, read it, then run it with {string.Join(' ', interpreter)} <file>",
    };
}
