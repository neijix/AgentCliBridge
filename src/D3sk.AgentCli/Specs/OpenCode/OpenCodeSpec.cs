namespace D3sk.AgentCli.Specs.OpenCode;

/// <summary>What the bridge knows about OpenCode, used as the OpenRouter client: its names, curated models and install hint.</summary>
public static class OpenCodeSpec
{
    /// <summary>The canonical command, also the bridge's agent id.</summary>
    public const string Command = "opencode";

    /// <summary>Display name: the CLI is <c>opencode</c>, the UI says Open Router.</summary>
    public const string Name = "Open Router";

    /// <summary>Spawn and stream adapter family.</summary>
    public const string Flavor = "opencode";

    /// <summary>Where to get the CLI and its OpenRouter key.</summary>
    public const string InstallHint =
        "Install OpenCode: brew install opencode — then run `opencode auth login -p openrouter` to store your OpenRouter key.";

    /// <summary>Names resolved on the PATH.</summary>
    public static IReadOnlyList<string> Aliases { get; } = ["opencode"];

    /// <summary>
    /// Curated <c>provider/model</c> ids (verified 2026-11-04 against OpenRouter's catalog and
    /// <c>opencode models</c>), passed verbatim to <c>--model</c>; the first is the default. Free and
    /// stealth models come and go. <c>opencode/*</c> needs no OpenRouter key.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } =
    [
        "openrouter/stealth/crouton-alpha",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/google/gemma-4-31b-it:free",
        "openrouter/google/gemma-4-26b-a4b-it:free",
        "openrouter/nvidia/nemotron-3.5-super-vl:free",
        "openrouter/nvidia/nemotron-3.5-lightning:free",
        "openrouter/cohere/north-mini-code:free",
        "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "openrouter/recursive/flint-v1.0:free",
        "openrouter/xingchen-agi/xing4.0-29b-a4b:free",
        "openrouter/dots-studio/dots-3-note-preview:free",
        "openrouter/liquid/lfm-2.5-2.6b:free",
        "opencode/big-pickle",
        "opencode/beam-free",
        "opencode/crouton-alpha-free",
        "opencode/deepseek-v4.1-flash-free",
        "opencode/flint-40b-free",
        "opencode/glm-5.3-flash-free",
        "opencode/mimo-v2.6-flash-free",
        "opencode/nemotron-3.5-lightning-free",
        "opencode/nemotron-3.5-super-vl-free",
        "opencode/pulse-alpha-free",
    ];
}
