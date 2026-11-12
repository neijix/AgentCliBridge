namespace D3sk.AgentCli.Settings;

/// <summary>Where the settings file is looked for: the process environment, the user's home and the app's own folder. Every part can be replaced, so a test never touches the real ones.</summary>
public sealed record SettingsLocation
{
    /// <summary>The settings file's name.</summary>
    public const string FileName = "agent_cli_bridge.json";

    /// <summary>The environment variable that names the shared settings folder; empty or <c>none</c> means this computer only.</summary>
    public const string ConfigLocalEnv = "AGENT_CLI_BRIDGE_CONFIG_LOCAL";

    /// <summary>The folder beside the app that holds the shared settings.</summary>
    public const string ConfigLocalFolder = "config.local";

    /// <summary>The value that turns the shared folder off.</summary>
    public const string LocalOnly = "none";

    /// <summary>Reads an environment variable; null reads the process environment.</summary>
    public Func<string, string?>? GetEnv { get; init; }

    /// <summary>The user's home folder; null uses the OS's.</summary>
    public string? Home { get; init; }

    /// <summary>The app's folder, whose <c>config.local/</c> is used when the environment names none; null = the running app's base folder.</summary>
    public string? AppFolder { get; init; }

    internal string? Env(string name) => (GetEnv ?? Environment.GetEnvironmentVariable)(name);

    internal string HomeFolder => Home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

    /// <summary>
    /// The folder whose settings file is the shared one; null = this computer only. The environment's
    /// folder when set (empty or <c>none</c> = local only), else the app folder's <c>config.local/</c>.
    /// The folder may not exist.
    /// </summary>
    public string? ConfigLocalDir()
    {
        var pinned = Env(ConfigLocalEnv);
        if (pinned is not null)
        {
            pinned = pinned.Trim();
            return pinned.Length == 0 || pinned == LocalOnly ? null : ExpandHome(pinned);
        }
        var app = AppFolder ?? AppContext.BaseDirectory;
        return string.IsNullOrEmpty(app) ? null : Path.Combine(app, ConfigLocalFolder);
    }

    /// <summary>The settings file in use: <c>config.local/agent_cli_bridge.json</c> when that file exists, else the local-only <c>~/.agent_cli_bridge.json</c>.</summary>
    public string ConfigPath()
    {
        if (ConfigLocalDir() is { } folder)
        {
            if (Env(ConfigLocalEnv) is null) LegacyMigration.TryOnce(this, folder);
            var candidate = Path.Combine(folder, FileName);
            if (File.Exists(candidate)) return candidate;
        }
        return Path.Combine(HomeFolder, "." + FileName);
    }

    private string ExpandHome(string path)
    {
        if (path == "~") return HomeFolder;
        return path.StartsWith("~/", StringComparison.Ordinal) || path.StartsWith("~\\", StringComparison.Ordinal)
            ? Path.Combine(HomeFolder, path[2..]) : path;
    }

    internal string Expand(string path) => ExpandHome(path);
}
