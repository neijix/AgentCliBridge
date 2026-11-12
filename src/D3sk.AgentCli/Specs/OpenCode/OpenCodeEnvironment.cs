using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Specs.OpenCode;

/// <summary>The environment OpenCode is started with: the project folder and a stream-stall timeout.</summary>
public static class OpenCodeEnvironment
{
    /// <summary>
    /// Milliseconds of silence after which OpenCode aborts a provider stream and retries it. By default
    /// it has none: a stealth model that stopped mid-stream left a turn waiting 29 minutes. OpenRouter
    /// sends keep-alive comments while a model thinks and those count, so only a dead stream trips it.
    /// </summary>
    public const int ChunkTimeoutMs = 120_000;

    /// <summary>Name of the variable that carries OpenCode's inline configuration.</summary>
    public const string ConfigVariable = "OPENCODE_CONFIG_CONTENT";

    /// <summary>
    /// Points OpenCode at the project without <c>--dir</c>: it uses the process cwd, and OpenCode 1 read
    /// <c>PWD</c> before that, so the same path is published there. No folder leaves <paramref name="env"/> alone.
    /// </summary>
    public static void Directory(IDictionary<string, string> env, string? cwd)
    {
        if (!string.IsNullOrEmpty(cwd)) env["PWD"] = cwd;
    }

    /// <summary>
    /// <see cref="ConfigVariable"/> adding <see cref="ChunkTimeoutMs"/> for the model's provider, merged into
    /// <paramref name="current"/> (the value already in the environment). Null leaves the environment alone:
    /// no provider in the id, a value that is not a JSON object, or a chunkTimeout the host already chose.
    /// </summary>
    /// <param name="model">OpenCode's <c>provider/model</c> id.</param>
    /// <param name="current">The variable's present value, or null.</param>
    public static string? ConfigContent(string? model, string? current)
    {
        var id = (model ?? "").Trim();
        var slash = id.IndexOf('/');
        if (slash <= 0) return null;
        var provider = id[..slash];
        JsonObject config;
        try
        {
            config = string.IsNullOrEmpty(current) ? [] : JsonNode.Parse(current) as JsonObject ?? throw new JsonException();
        }
        catch (JsonException)
        {
            return null;
        }

        if (!Child(config, "provider", out var providers) || !Child(providers, provider, out var entry)
            || !Child(entry, "options", out var options) || options.ContainsKey("chunkTimeout"))
            return null;
        options["chunkTimeout"] = ChunkTimeoutMs;
        return config.ToJsonString();
    }

    /// <summary>The object under <paramref name="key"/>, created when absent; false when something else is there.</summary>
    private static bool Child(JsonObject parent, string key, out JsonObject child)
    {
        if (!parent.TryGetPropertyValue(key, out var node))
        {
            child = [];
            parent[key] = child;
            return true;
        }

        child = node as JsonObject ?? [];
        return node is JsonObject;
    }
}
