using System.Collections.Concurrent;

namespace D3sk.AgentCli.Settings;

// legacy apps-config migration — remove after 2027-01
// Until config.local/, the settings lived in <apps-config root>/AgentCliBridge/ (a synced folder
// named by $APPS_CONFIG_DIR or ~/.apps-config-dir). The one-time copy here is its only reader.

/// <summary>The one-time copy of a settings file left in the retired apps-config folder into <c>config.local/</c>.</summary>
public static class LegacyMigration
{
    private const string AppName = "AgentCliBridge";
    private static readonly ConcurrentDictionary<string, bool> Tried = new();

    /// <summary>The retired <c>&lt;root&gt;/AgentCliBridge</c> folder when it exists, else null; the root is <c>$APPS_CONFIG_DIR</c>, else the first line of <c>~/.apps-config-dir</c>.</summary>
    public static string? AppsConfigDir(SettingsLocation where)
    {
        var root = where.Env("APPS_CONFIG_DIR");
        if (root is null)
        {
            try { root = File.ReadLines(Path.Combine(where.HomeFolder, ".apps-config-dir")).FirstOrDefault() ?? ""; }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
        }
        root = root.Trim();
        if (root.Length == 0 || root == SettingsLocation.LocalOnly) return null;
        var folder = Path.Combine(where.Expand(root), AppName);
        return Directory.Exists(folder) ? folder : null;
    }

    /// <summary>
    /// Copies the settings file into <paramref name="target"/> while it has none; never overwrites,
    /// never deletes the source, and goes through a temp file so half a copy never looks like settings.
    /// Returns the file copied, null when there was nothing to copy; throws <see cref="IOException"/> on a failed copy.
    /// </summary>
    public static string? Migrate(SettingsLocation where, string target)
    {
        if (File.Exists(Path.Combine(target, SettingsLocation.FileName))) return null;
        var legacy = AppsConfigDir(where) is { } dir ? Path.Combine(dir, SettingsLocation.FileName) : null;
        if (legacy is null || !File.Exists(legacy)) return null;
        Directory.CreateDirectory(target);
        // a temp name of its own: two processes starting together never remove each other's
        var temp = Path.Combine(target, $".{SettingsLocation.FileName}.{Guid.NewGuid():N}.migrating");
        try
        {
            File.Copy(legacy, temp);
            File.Move(temp, Path.Combine(target, SettingsLocation.FileName), overwrite: false);
        }
        finally
        {
            try { File.Delete(temp); } catch (IOException) { }
        }
        return legacy;
    }

    /// <summary>Runs <see cref="Migrate"/> the first time this process reads <paramref name="target"/>; never throws.</summary>
    internal static void TryOnce(SettingsLocation where, string target)
    {
        if (!Tried.TryAdd(target, true)) return;
        try { Migrate(where, target); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { /* a cloud placeholder can stat fine and still fail to open: settings stay as they are */ }
    }
}
