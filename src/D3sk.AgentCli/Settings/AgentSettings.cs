using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Host;

namespace D3sk.AgentCli.Settings;

/// <summary>What reading the settings gave: the options for discovery, the file used and, when it was ignored, why.</summary>
/// <param name="Options">The discovery options; the built-in defaults when the file is missing or unusable.</param>
/// <param name="Path">The file that was read, or null when none exists.</param>
/// <param name="Reason">Why the file was ignored (unreadable, not JSON, not an object); null otherwise.</param>
public sealed record SettingsResult(DiscoveryOptions Options, string? Path, string? Reason);

/// <summary>The shared <c>agent_cli_bridge.json</c>: <c>disabled_agents</c> and <c>models</c> read into <see cref="DiscoveryOptions"/>, <c>disabled_agents</c> written back when a CLI is signed in.</summary>
public static class AgentSettings
{
    private static readonly JsonSerializerOptions Pretty = new() { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    /// <summary>Reads the settings. A missing, unreadable or malformed file gives the defaults and a reason, never an exception.</summary>
    public static SettingsResult Load(SettingsLocation? where = null)
    {
        var path = (where ?? new SettingsLocation()).ConfigPath();
        var (config, reason) = Read(path);
        return new SettingsResult(ToOptions(config), config is null && reason is null ? null : path, reason);
    }

    /// <summary>The discovery options for a parsed settings object; a null one means the defaults.</summary>
    public static DiscoveryOptions ToOptions(JsonObject? config) => new()
    {
        Disabled = new HashSet<string>(DisabledNames(config)),
        ModelOverrides = ModelTable(config),
    };

    /// <summary>
    /// Drops <paramref name="names"/> (commands or flavors) from the file's <c>disabled_agents</c>; the rest
    /// of the file is kept. Nothing is written when none is listed or the file is missing or unusable;
    /// the write goes through a temp file so a reader never sees half of it.
    /// </summary>
    public static void EnableAgents(IReadOnlySet<string> names, SettingsLocation? where = null)
    {
        var path = (where ?? new SettingsLocation()).ConfigPath();
        if (Read(path).Config is not { } config) return;
        var listed = DisabledNames(config);
        var kept = listed.Where(n => !names.Contains(n)).ToList();
        if (kept.Count == listed.Count) return;
        var array = new JsonArray();
        foreach (var name in kept) array.Add((JsonNode?)JsonValue.Create(name));
        config["disabled_agents"] = array;
        var temp = Path.Combine(Path.GetDirectoryName(path) ?? ".", $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllText(temp, config.ToJsonString(Pretty) + "\n");
            File.Move(temp, path, overwrite: true);
        }
        finally
        {
            try { File.Delete(temp); } catch (IOException) { }
        }
    }

    private static (JsonObject? Config, string? Reason) Read(string path)
    {
        string text;
        try
        {
            if (!File.Exists(path)) return (null, null);
            text = File.ReadAllText(path);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return (null, $"{path} could not be read: {e.Message}");
        }
        try
        {
            if (JsonNode.Parse(text) is not JsonObject config) return (null, $"{path} is not a JSON object");
            _ = config.ContainsKey(""); // the parser reports a duplicate key only on first lookup
            return (config, null);
        }
        catch (Exception e) when (e is JsonException or ArgumentException)
        {
            return (null, $"{path} is not valid JSON: {e.Message}");
        }
    }

    private static List<string> DisabledNames(JsonObject? config) =>
        config?["disabled_agents"] is JsonArray listed
            ? [.. listed.Select(i => i is JsonValue v && v.TryGetValue<string>(out var s) ? s : null).OfType<string>()]
            : [];

    private static Dictionary<string, IReadOnlyList<string>> ModelTable(JsonObject? config)
    {
        var table = new Dictionary<string, IReadOnlyList<string>>();
        if (config?["models"] is not JsonObject models) return table;
        foreach (var (key, value) in models)
        {
            // a value that is not a list names nothing; an empty list falls back to the curated one
            if (value is not JsonArray names) continue;
            table[key] = [.. names.Select(n => n is JsonValue v && v.TryGetValue<string>(out var s) ? s : null).OfType<string>().Where(s => s.Length > 0)];
        }
        return table;
    }
}
