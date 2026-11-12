using D3sk.AgentCli.Specs.Agy;
using D3sk.AgentCli.Specs.Claude;
using D3sk.AgentCli.Specs.Copilot;
using D3sk.AgentCli.Specs.Cursor;
using D3sk.AgentCli.Specs.Gemini;
using D3sk.AgentCli.Specs.Grok;
using D3sk.AgentCli.Specs.OpenCode;

namespace D3sk.AgentCli.Host;

/// <summary>A local CLI coding agent the bridge knows how to spawn: the vendor's official binary, signed in by the user.</summary>
/// <param name="Command">The canonical command, also the bridge's agent id.</param>
/// <param name="Name">Display name.</param>
/// <param name="Flavor">Spawn and stream adapter family: claude, cursor, antigravity, gemini, grok, copilot or opencode.</param>
/// <param name="Aliases">Names resolved on the PATH.</param>
/// <param name="AppMarkers">IDE app paths that count as "installed" even when the CLI is missing.</param>
/// <param name="InstallHint">Where to get the CLI.</param>
/// <param name="Models">Curated model ids passed verbatim to <c>--model</c>; the first is the default.</param>
public sealed record AgentSpec(
    string Command,
    string Name,
    string Flavor,
    IReadOnlyList<string> Aliases,
    IReadOnlyList<string> AppMarkers,
    string InstallHint,
    IReadOnlyList<string> Models);

/// <summary>The registry of the CLIs the bridge can run, in the order a picker lists them.</summary>
public static class AgentRegistry
{
    /// <summary>Every known CLI, in the registry's order.</summary>
    public static IReadOnlyList<AgentSpec> All { get; } =
    [
        new(ClaudeSpec.Command, ClaudeSpec.Name, ClaudeSpec.Flavor, ClaudeSpec.Aliases, [], ClaudeSpec.InstallHint, ClaudeSpec.Models),
        new(CursorSpec.Command, CursorSpec.Name, CursorSpec.Flavor, CursorSpec.Aliases, [CursorSpec.AppMarker], CursorSpec.InstallHint, CursorSpec.Models),
        new(AgySpec.Command, AgySpec.Name, AgySpec.Flavor, AgySpec.Aliases, AgySpec.AppMarkers, AgySpec.InstallHint, AgySpec.Models),
        new(GrokSpec.Command, GrokSpec.Name, GrokSpec.Flavor, GrokSpec.Aliases, [], GrokSpec.InstallHint, GrokSpec.Models),
        new(GeminiSpec.Command, GeminiSpec.Name, GeminiSpec.Flavor, GeminiSpec.Aliases, [], GeminiSpec.InstallHint, GeminiSpec.Models),
        new(CopilotSpec.Command, CopilotSpec.Name, CopilotSpec.Flavor, CopilotSpec.Aliases, [], CopilotSpec.InstallHint, CopilotSpec.Models),
        new(OpenCodeSpec.Command, OpenCodeSpec.Name, OpenCodeSpec.Flavor, OpenCodeSpec.Aliases, [], OpenCodeSpec.InstallHint, OpenCodeSpec.Models),
    ];

    /// <summary>The spec for a command or one of its aliases, or null when unknown.</summary>
    public static AgentSpec? Find(string? command)
    {
        var name = (command ?? "").Trim();
        return All.FirstOrDefault(s => s.Command == name) ?? All.FirstOrDefault(s => s.Aliases.Contains(name));
    }

    /// <summary>A command's adapter flavor; an unknown command is treated as claude.</summary>
    public static string FlavorFor(string? command) => Find(command)?.Flavor ?? ClaudeSpec.Flavor;

    /// <summary>
    /// A command's binary: its CLI's own discovery rule (PATH, <c>~/.local/bin</c> and the vendor's
    /// fallback folders). An unknown command is looked up by its own name. A dangling link or a file
    /// that is not executable is not a binary. Null when nothing usable is found.
    /// </summary>
    /// <param name="command">A command or alias.</param>
    /// <param name="pathEnv">The PATH value; null reads the process environment.</param>
    /// <param name="home">The user's home folder; null reads the profile folder.</param>
    /// <param name="localAppData">Windows' local app data folder (Antigravity's layout); null reads it.</param>
    /// <param name="isUsable">Probe for an executable file; null checks the file system.</param>
    public static string? ResolveBinary(
        string? command, string? pathEnv = null, string? home = null, string? localAppData = null, Func<string, bool>? isUsable = null)
    {
        var name = (command ?? "").Trim();
        if (name.Length == 0) return null;
        return Find(name)?.Flavor switch
        {
            "cursor" => CursorDiscovery.Resolve(pathEnv, home, isUsable),
            "antigravity" => AgyDiscovery.Resolve(pathEnv, home, isUsable, localAppData),
            "grok" => GrokDiscovery.Resolve(pathEnv, isUsable),
            "gemini" => GeminiDiscovery.Resolve(pathEnv, home, isUsable),
            "copilot" => CopilotDiscovery.Resolve(pathEnv, home, isUsable),
            "opencode" => OpenCodeDiscovery.Resolve(pathEnv, home, isUsable),
            "claude" => ClaudeDiscovery.Resolve(pathEnv, home, isUsable),
            _ => ClaudeDiscovery.ResolveAliases([name], pathEnv, home, isUsable),
        };
    }
}
