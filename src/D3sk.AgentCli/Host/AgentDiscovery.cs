using D3sk.AgentCli.Specs.Cursor;

namespace D3sk.AgentCli.Host;

/// <summary>One CLI as discovery found it on this machine.</summary>
/// <param name="Command">The canonical command.</param>
/// <param name="Name">Display name.</param>
/// <param name="Path">The resolved binary, or null.</param>
/// <param name="Flavor">The adapter family.</param>
/// <param name="Models">The models to offer: the settings' override, else the curated list.</param>
/// <param name="BinaryFound">A usable binary was found.</param>
/// <param name="InstallHint">Where to get the CLI; empty once its binary is found.</param>
public sealed record AgentInfo(
    string Command, string Name, string? Path, string Flavor, IReadOnlyList<string> Models, bool BinaryFound, string InstallHint);

/// <summary>What discovery reads besides the machine: the settings file's choices and the probes.</summary>
public sealed record DiscoveryOptions
{
    /// <summary>Commands or flavors the settings turn off: never listed, never offered.</summary>
    public IReadOnlySet<string> Disabled { get; init; } = new HashSet<string>();

    /// <summary>Model lists from the settings, keyed by command or flavor (the command wins); an empty list falls back to the curated one.</summary>
    public IReadOnlyDictionary<string, IReadOnlyList<string>> ModelOverrides { get; init; } = new Dictionary<string, IReadOnlyList<string>>();

    /// <summary>Finds a command's binary; null uses <see cref="AgentRegistry.ResolveBinary"/>.</summary>
    public Func<string, string?>? ResolveBinary { get; init; }

    /// <summary>Whether a vendor IDE app path exists; null checks the file system.</summary>
    public Func<string, bool>? AppExists { get; init; }
}

/// <summary>Which CLIs this machine has, and the one rule every app built on AgentCli uses to offer them.</summary>
public static class AgentDiscovery
{
    /// <summary>
    /// The CLIs found by a binary or by their IDE app, in the registry's order, without the disabled
    /// ones; each carries the settings' model list when one is set.
    /// </summary>
    public static IReadOnlyList<AgentInfo> Discover(DiscoveryOptions? options = null)
    {
        options ??= new DiscoveryOptions();
        var resolve = options.ResolveBinary ?? (c => AgentRegistry.ResolveBinary(c));
        var exists = options.AppExists ?? (p => File.Exists(p) || Directory.Exists(p));
        var found = new List<AgentInfo>();
        foreach (var spec in AgentRegistry.All)
        {
            if (options.Disabled.Contains(spec.Command) || options.Disabled.Contains(spec.Flavor)) continue;
            var binary = resolve(spec.Command);
            if (binary is null && !spec.AppMarkers.Any(exists)) continue;
            found.Add(new AgentInfo(spec.Command, spec.Name, binary, spec.Flavor, ModelsFor(spec, options), binary is not null,
                binary is null ? spec.InstallHint : ""));
        }
        return found;
    }

    /// <summary>
    /// Whether a host offers this entry: a CLI binary was found and it is not Cursor's <c>agent</c> name
    /// resolving to Grok's own binary. (A disabled agent never reaches this point.)
    /// </summary>
    public static bool IsAvailable(AgentInfo agent) => agent.BinaryFound && !IsCursorGrokCollision(agent);

    /// <summary>The agents a host offers the user: what <see cref="Discover"/> finds with a binary and no collision.</summary>
    public static IReadOnlyList<AgentInfo> Available(DiscoveryOptions? options = null) =>
        [.. Discover(options).Where(IsAvailable)];

    /// <summary>
    /// Cursor's generic <c>agent</c> name resolving to Grok CLI's binary: such an entry is Grok, and
    /// listing, running or updating it as Cursor would drive the wrong CLI. Grok's own entry never is one.
    /// </summary>
    public static bool IsCursorGrokCollision(AgentInfo agent)
    {
        var command = agent.Command.Trim().ToLowerInvariant();
        var isCursor = command is "agent" or "cursor-agent" || agent.Flavor.Trim().Equals("cursor", StringComparison.OrdinalIgnoreCase);
        return isCursor && CursorDiscovery.IsGrokCollision(agent.Path);
    }

    /// <summary>Why a Cursor entry that is Grok's binary is never run, updated or signed in.</summary>
    public static string CollisionRefusal(string name, string? path) =>
        $"{name} on this machine resolves to {(string.IsNullOrEmpty(path) ? "(unknown path)" : path)} — that is Grok CLI's own binary, not Cursor's. " +
        "Refusing to use it as Cursor. Install Cursor Agent separately and correct the PATH collision.";

    private static IReadOnlyList<string> ModelsFor(AgentSpec spec, DiscoveryOptions options)
    {
        foreach (var key in new[] { spec.Command, spec.Flavor })
        {
            // the first key with a list wins, even an empty one, which means "the curated list"
            if (options.ModelOverrides.TryGetValue(key, out var names)) return names.Count > 0 ? names : Curated(spec);
        }
        return Curated(spec);
    }

    private static IReadOnlyList<string> Curated(AgentSpec spec) => spec.Models.Count > 0 ? spec.Models : [spec.Command];
}
