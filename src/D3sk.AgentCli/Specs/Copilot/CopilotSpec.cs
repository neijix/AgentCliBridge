namespace D3sk.AgentCli.Specs.Copilot;

/// <summary>What the bridge knows about GitHub Copilot CLI: its names, curated models and install hint.</summary>
public static class CopilotSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "copilot";

    /// <summary>Display name.</summary>
    public const string Name = "GitHub Copilot CLI";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "copilot";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint =
        "Install GitHub Copilot CLI: npm install -g @github/copilot — then run `copilot` once to sign in with your GitHub account.";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["copilot"];

    /// <summary>
    /// Curated model ids passed verbatim to <c>--model</c>; the first is the default. "auto" lets Copilot
    /// pick (documented in its <c>--help</c>); claude-sonnet-5 is the observed default; gpt-5-mini is an
    /// included (non-premium) model.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } = ["auto", "claude-sonnet-5", "gpt-5-mini"];
}
