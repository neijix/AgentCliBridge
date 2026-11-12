namespace D3sk.AgentCli.Specs.Grok;

/// <summary>What the bridge knows about the Grok CLI: its names, curated models and install hint.</summary>
public static class GrokSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "grok";

    /// <summary>Display name.</summary>
    public const string Name = "Grok CLI";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "grok";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint = "Install Grok CLI: npm install -g @xai-official/grok";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["grok"];

    /// <summary>Curated model ids; a <c>-high</c> or <c>-low</c> suffix becomes <c>--reasoning-effort</c>. The first is the default.</summary>
    public static IReadOnlyList<string> Models { get; } = ["grok-4.6", "grok-4.6-high", "grok-4.5"];
}
