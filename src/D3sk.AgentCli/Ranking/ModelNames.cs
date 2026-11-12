using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Ranking;

/// <summary>The names a CLI and a model show under. The id sent to the CLI is never changed.</summary>
public static class ModelNames
{
    private const string Separator = "::";

    /// <summary>The key a (command, model) pair is stored under.</summary>
    public static string ModelKey(string command, string model) => $"{command}{Separator}{model}";

    /// <summary>The CLI is still <c>opencode</c>, the UI says Open Router. Claude on a personal subscription and through a company gateway read apart.</summary>
    public static string AgentDisplayName(CatalogAgent? agent)
    {
        if (agent is null)
        {
            return "";
        }

        if (agent.Command == "opencode")
        {
            return "Open Router";
        }

        var name = !string.IsNullOrEmpty(agent.Name) ? agent.Name : agent.Command;
        return agent.AccountKind is "personal" or "work" ? $"{name} ({agent.AccountKind})" : name;
    }

    /// <summary>The name a company gateway gives one of Claude Code's models, or "". <c>labels</c> comes from another machine: only an own, non-empty entry counts.</summary>
    public static string ModelLabel(IReadOnlyDictionary<string, string>? labels, string model) =>
        labels is not null && labels.TryGetValue(model, out var label) ? label ?? "" : "";

    /// <summary>OpenCode Zen ids (<c>opencode/x</c>) show as Open Router ids, a local MLX model without its HuggingFace org, a gateway-named model by its label.</summary>
    public static string ModelDisplayName(string? model, IReadOnlyDictionary<string, string>? labels = null)
    {
        if (string.IsNullOrEmpty(model))
        {
            return "";
        }

        if (ModelLabel(labels, model) is { Length: > 0 } label)
        {
            return label;
        }

        if (model.StartsWith("opencode/", StringComparison.Ordinal))
        {
            return $"openrouter/{model["opencode/".Length..]}";
        }

        return model.StartsWith("mlx-community/", StringComparison.Ordinal) ? model["mlx-community/".Length..] : model;
    }
}
