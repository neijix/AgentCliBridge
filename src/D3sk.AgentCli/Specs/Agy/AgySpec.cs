namespace D3sk.AgentCli.Specs.Agy;

/// <summary>What the bridge knows about Google Antigravity's CLI (<c>agy</c>): its names, curated models and install hint.</summary>
public static class AgySpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "agy";

    /// <summary>Display name.</summary>
    public const string Name = "Google Antigravity";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "antigravity";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint =
        "Install Antigravity CLI: curl -fsSL https://antigravity.google/cli/install.sh | bash " +
        "(Windows: winget install -e --id Google.AntigravityCLI)";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["agy"];

    /// <summary>IDE app paths that count as "installed" even when the CLI is missing.</summary>
    public static IReadOnlyList<string> AppMarkers { get; } = ["/Applications/Antigravity.app"];

    /// <summary>
    /// Curated model ids passed verbatim to <c>--model</c>, as <c>agy models</c> lists them (verified
    /// 2026-11-16, CLI 1.5.9: an id it no longer lists fails the turn before it starts). "default" stays
    /// first so settings that stored it still resolve to the CLI's own default.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } =
    [
        "default",
        "gemini-4-argon-medium",
        "gemini-4-argon-high",
        "gemini-4-argon-low",
        "gemini-4-hydrogen-high",
        "gemini-4-hydrogen-xhigh",
        "gemini-4-hydrogen-medium",
        "gemini-4-hydrogen-low",
        "gemini-3.8-flash-high",
        "gemini-3.8-flash-medium",
        "gemini-3.8-flash-low",
        "claude-opus-5-5-low",
        "claude-opus-5-5-medium",
        "claude-opus-5-5-high",
        "claude-sonnet-5-5-low",
        "claude-sonnet-5-5-medium",
        "claude-sonnet-5-5-high",
        "gpt-oss-120b-medium",
    ];
}
