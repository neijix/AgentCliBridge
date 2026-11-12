namespace D3sk.AgentCli.Specs.Cursor;

/// <summary>What the bridge knows about Cursor Agent: its names, curated models and install hint.</summary>
public static class CursorSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "agent";

    /// <summary>Display name.</summary>
    public const string Name = "Cursor Agent";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "cursor";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint = "Install Cursor Agent CLI: curl https://cursor.com/install -fsS | bash";

    /// <summary>The vendor IDE whose presence suggests the CLI may be missing rather than unwanted.</summary>
    public const string AppMarker = "/Applications/Cursor.app";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["agent", "cursor-agent"];

    /// <summary>
    /// A curated shortlist of current flagships from <c>cursor-agent models</c> (verified 2026-09-30; the
    /// CLI exposes about 245 ids across effort and fast tiers). The first is the default: "auto" lets
    /// Cursor pick. Parameterized overrides (for example <c>claude-opus-5[effort=high]</c>) travel in
    /// the extra argv.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } =
    [
        "auto",
        "composer-2.5",
        "grok-4.7-high",
        "cursor-grok-4.6-high",
        "claude-opus-5-5-high",
        "claude-fable-5-1-high",
        "claude-sonnet-5-5-high",
        "claude-opus-5-thinking-high",
        "gpt-5.6-sol-high",
        "gpt-5.3-codex",
    ];
}
