using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.WebScout;

/// <summary>
/// Claude Code keeps only the last <c>--settings</c>: every one in an argument list is folded into one, so the
/// scout's ask rules do not cost the host's own settings.
/// </summary>
public static class SettingsArgs
{
    private static readonly JsonSerializerOptions Compact = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    /// <summary>
    /// Folds every <c>--settings</c> (inline JSON or a JSON file; later keys win, <c>permissions</c> rule lists are
    /// concatenated) into one appended at the end. Unreadable values are dropped; fewer than two leave the list as is.
    /// </summary>
    public static List<string> Merge(IReadOnlyList<string> args)
    {
        var rest = new List<string>();
        var values = new List<string>();
        for (var i = 0; i < args.Count; i++)
        {
            if (args[i] == "--settings" && i + 1 < args.Count)
            {
                values.Add(args[++i]);
            }
            else if (args[i].StartsWith("--settings=", StringComparison.Ordinal))
            {
                values.Add(args[i]["--settings=".Length..]);
            }
            else
            {
                rest.Add(args[i]);
            }
        }
        if (values.Count < 2)
        {
            return [.. args];
        }
        var merged = new JsonObject();
        foreach (var parsed in values.Select(Read).OfType<JsonObject>())
        {
            Fold(merged, parsed);
        }
        return [.. rest, "--settings", merged.ToJsonString(Compact)];
    }

    private static JsonObject? Read(string value)
    {
        var text = value.Trim();
        try
        {
            if (!text.StartsWith('{'))
            {
                text = File.ReadAllText(text.StartsWith("~/", StringComparison.Ordinal)
                    ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), text[2..])
                    : text);
            }
            return JsonNode.Parse(text) as JsonObject;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException or ArgumentException)
        {
            return null; // dropped: a settings value that cannot be read
        }
    }

    private static void Fold(JsonObject into, JsonObject extra)
    {
        foreach (var (key, value) in extra)
        {
            if (key == "permissions" && value is JsonObject added && into[key] is JsonObject have)
            {
                into[key] = FoldPermissions(have, added);
            }
            else
            {
                into[key] = value?.DeepClone();
            }
        }
    }

    private static JsonObject FoldPermissions(JsonObject have, JsonObject added)
    {
        var merged = (JsonObject)have.DeepClone();
        foreach (var (ruleKey, rules) in added)
        {
            if (rules is JsonArray list && merged[ruleKey] is JsonArray existing)
            {
                var kept = existing.Select(r => r?.ToJsonString()).ToHashSet();
                foreach (var rule in list.Where(r => !kept.Contains(r?.ToJsonString())))
                {
                    existing.Add(rule?.DeepClone());
                }
            }
            else
            {
                merged[ruleKey] = rules?.DeepClone();
            }
        }
        return merged;
    }
}
