namespace D3sk.AgentCli.Specs.Claude;

/// <summary>What the bridge knows about Claude Code: its names, curated models and install hint.</summary>
public static class ClaudeSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "claude";

    /// <summary>Display name.</summary>
    public const string Name = "Claude Code";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "claude";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint = "Install Claude Code: https://claude.ai/code";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["claude"];

    /// <summary>
    /// Curated model ids passed verbatim to <c>--model</c>; the first is the default. The short aliases
    /// always resolve to the latest release; <c>claude-opus-5-5</c> pins Opus 5.5 by its full id.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } = ["sonnet", "fable", "opus", "claude-opus-5-5", "haiku"];
}
