namespace D3sk.AgentCli.Specs.Gemini;

/// <summary>What the bridge knows about Gemini CLI: its names, curated models and install hint.</summary>
public static class GeminiSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "gemini";

    /// <summary>Display name.</summary>
    public const string Name = "Gemini CLI";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "gemini";

    /// <summary>Where to get the CLI.</summary>
    public const string InstallHint =
        "Install Gemini CLI: npm install -g @google/gemini-cli — then run `gemini` once and choose 'Login with Google' (no API key needed).";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["gemini"];

    /// <summary>Curated model ids, as the CLI's own <c>--help</c> names them; the first is the default.</summary>
    public static IReadOnlyList<string> Models { get; } =
        ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"];
}
