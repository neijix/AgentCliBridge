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
    /// Preferred order of Open Router's free models (its catalog on 2026-11-16), passed verbatim to
    /// <c>--model</c>. Only what <c>opencode models</c> lists is offered (it lists Open Router models
    /// once a key is stored); an id here it does not list is not shown. Free models come and go.
    /// </summary>
    public static IReadOnlyList<string> Models { get; } =
    [
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/thinkingmachines/inkling-2-small:free",
        "openrouter/inclusionai/ling-3.2-flash:free",
        "openrouter/particle-ai/particle-1:free",
        "openrouter/baidu/ernie-5.5-flash-preview:free",
        "openrouter/nvidia/nemotron-3.5-super-vl:free",
        "openrouter/nvidia/nemotron-3.5-lightning:free",
        "openrouter/dots-studio/dots-3-note-preview:free",
        "openrouter/google/gemma-4-31b-it:free",
        "openrouter/google/gemma-4-26b-a4b-it:free",
        "openrouter/cohere/north-mini-code:free",
        "openrouter/recursive/flint-v1.0:free",
        "openrouter/liquid/lfm-3-1.7b:free",
        "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    ];
}
