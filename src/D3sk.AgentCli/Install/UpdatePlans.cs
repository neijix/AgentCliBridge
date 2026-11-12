using System.Text.RegularExpressions;
using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Install;

/// <summary>
/// Update and uninstall plans from where the binary really lives, so the copy the host runs is the
/// one touched and no second one lands beside it: a Homebrew cask or formula goes through that
/// Homebrew, an npm global through the npm next to it, anything else through the CLI's own updater.
/// </summary>
public static partial class UpdatePlans
{
    /// <summary>npm package of each npm-published CLI: the one table the status checks read too.</summary>
    public static IReadOnlyDictionary<string, string> NpmPackages => Status.ReleaseSources.NpmPackages;

    /// <summary>A Homebrew cask whose newest version is not the one the foot compares with, and its <c>@latest</c> twin.</summary>
    public static IReadOnlyDictionary<string, string> CaskLatestTwin { get; } = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["claude-code"] = "claude-code@latest",
    };

    /// <summary>CLIs that update themselves when Homebrew and npm did not install them.</summary>
    public static IReadOnlyDictionary<string, string> SelfUpdate { get; } = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["claude"] = "update",
        ["agent"] = "update",
        ["cursor-agent"] = "update",
        ["agy"] = "update",
        ["grok"] = "update",
        ["opencode"] = "upgrade",
    };

    private static readonly Dictionary<string, string> WingetPackages = new(StringComparer.Ordinal)
    {
        ["copilot"] = "GitHub.Copilot",
        ["agy"] = "Google.AntigravityCLI",
    };

    [GeneratedRegex(@"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")]
    private static partial Regex NpmPackageName();

    /// <summary>How to update <paramref name="command"/>; <paramref name="resolved"/> is <paramref name="binary"/> with symlinks followed.</summary>
    public static CliPlan Update(string command, string binary, string resolved, bool isWindows = false, Func<string, string>? tool = null)
    {
        tool ??= n => CliTools.WindowsTool(n);
        var parts = CliPath.Parts(resolved, isWindows);
        if (BrewPrefix(parts, "Caskroom", isWindows) is { } cask)
        {
            var token = parts[cask.At + 1];
            if (CaskLatestTwin.TryGetValue(token, out var twin))
            {
                return new CliPlan
                {
                    Argv = [cask.Brew, "fetch", "--cask", twin],
                    Then = [[cask.Brew, "uninstall", "--cask", token], [cask.Brew, "install", "--cask", twin]],
                    How = $"Homebrew — the {token} cask tracks the stable channel; switching to {twin}",
                };
            }
            return new CliPlan { Argv = [cask.Brew, "upgrade", "--cask", token], How = "Homebrew" };
        }
        if (BrewPrefix(parts, "Cellar", isWindows) is { } cellar)
        {
            return new CliPlan { Argv = [cellar.Brew, "upgrade", parts[cellar.At + 1]], How = "Homebrew" };
        }
        if (NpmGlobal(parts, isWindows) is { } npm)
        {
            return new CliPlan { Argv = [npm.Npm, "install", "-g", $"{npm.Package}@latest"], How = "npm" };
        }
        if (isWindows && command == "copilot" && WingetPackage(command, parts) is not null)
        {
            return new CliPlan
            {
                Argv =
                [
                    tool("winget"), "upgrade", "--id", "GitHub.Copilot", "--exact", "--source", "winget",
                    "--silent", "--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements",
                ],
                How = "WinGet",
            };
        }
        var package = NpmPackages.GetValueOrDefault(command, "");
        if (isWindows && package.Length > 0 && IsShim(binary))
        {
            // Shims live in the global prefix, but npm.cmd usually lives beside node.exe: pin the
            // destination so another npm on PATH cannot update a different installation.
            return new CliPlan
            {
                Argv = [tool("npm.cmd"), "install", "-g", "--prefix", CliPath.Parent(binary, true), $"{package}@latest"],
                How = "npm",
            };
        }
        if (SelfUpdate.TryGetValue(command, out var verb) && binary.Length > 0)
        {
            return new CliPlan { Argv = [binary, verb], How = "its own updater" };
        }
        return new CliPlan { Hint = package.Length > 0 ? $"npm install -g {package}@latest" : "update it the way it was installed" };
    }

    /// <summary>How to remove <paramref name="command"/>, or a hint when the host cannot remove it itself.</summary>
    public static CliPlan Uninstall(string command, string binary, string resolved, bool isWindows = false, string? home = null, Func<string, string>? tool = null)
    {
        tool ??= n => CliTools.WindowsTool(n);
        var parts = CliPath.Parts(resolved, isWindows);
        if (BrewPrefix(parts, "Caskroom", isWindows) is { } cask)
        {
            return new CliPlan { Argv = [cask.Brew, "uninstall", "--cask", parts[cask.At + 1]], How = "Homebrew" };
        }
        if (BrewPrefix(parts, "Cellar", isWindows) is { } cellar)
        {
            return new CliPlan { Argv = [cellar.Brew, "uninstall", parts[cellar.At + 1]], How = "Homebrew" };
        }
        if (NpmGlobal(parts, isWindows) is { } npm)
        {
            return new CliPlan { Argv = [npm.Npm, "uninstall", "-g", npm.Package], How = "npm" };
        }
        if (isWindows && WingetPackage(command, parts) is { } winget)
        {
            return new CliPlan
            {
                Argv =
                [
                    tool("winget"), "uninstall", "--id", winget, "--exact", "--source", "winget",
                    "--silent", "--disable-interactivity", "--accept-source-agreements",
                ],
                How = "WinGet",
            };
        }
        var package = NpmPackages.GetValueOrDefault(command, "");
        if (isWindows && package.Length > 0 && IsShim(binary))
        {
            return new CliPlan { Argv = [tool("npm.cmd"), "uninstall", "-g", "--prefix", CliPath.Parent(binary, true), package], How = "npm" };
        }
        var homeDir = home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var native = NativeInstalls.OwnBinInstall(command, resolved, homeDir) ?? (isWindows ? null : NativeInstalls.SelfInstalled(command, binary, resolved, homeDir));
        if (native is not null)
        {
            return new CliPlan { Remove = native, How = "its own install folder" };
        }
        var where = binary.Length > 0 ? $" ({binary})" : "";
        return new CliPlan { Hint = $"remove it the way it was installed{where}" };
    }

    private static bool IsShim(string binary) =>
        binary.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase) || binary.EndsWith(".ps1", StringComparison.OrdinalIgnoreCase);

    private static (string Brew, int At)? BrewPrefix(string[] parts, string folder, bool isWindows)
    {
        var at = Array.IndexOf(parts, folder);
        if (at < 0 || at + 1 >= parts.Length)
        {
            return null;
        }
        return (CliPath.Join([.. parts.Take(at), "bin", "brew"], isWindows), at);
    }

    private static (string Npm, string Package)? NpmGlobal(string[] parts, bool isWindows)
    {
        var at = Array.IndexOf(parts, "node_modules");
        if (at < 1 || parts[at - 1] != "lib" || at + 1 >= parts.Length)
        {
            return null;
        }
        var name = parts[at + 1];
        if (name.StartsWith('@') && at + 2 < parts.Length)
        {
            name = $"{name}/{parts[at + 2]}";
        }
        return NpmPackageName().IsMatch(name) ? (CliPath.Join([.. parts.Take(at - 1), "bin", "npm"], isWindows), name) : null;
    }

    private static string? WingetPackage(string command, string[] parts)
    {
        if (!WingetPackages.TryGetValue(command, out var package))
        {
            return null;
        }
        var prefix = package.ToLowerInvariant() + "_";
        var lowered = parts.Select(p => p.ToLowerInvariant()).ToArray();
        for (var i = 0; i < lowered.Length - 2; i++)
        {
            if (lowered[i] == "winget" && lowered[i + 1] == "packages" && lowered[i + 2].StartsWith(prefix, StringComparison.Ordinal))
            {
                return package;
            }
        }
        return null;
    }
}
