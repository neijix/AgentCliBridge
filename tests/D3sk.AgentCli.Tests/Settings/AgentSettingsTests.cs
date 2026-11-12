using D3sk.AgentCli.Host;
using D3sk.AgentCli.Settings;

namespace D3sk.AgentCli.Tests.Settings;

public sealed class AgentSettingsTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("acb-settings-").FullName;
    private readonly Dictionary<string, string?> _env = [];

    private string Folder(string name)
    {
        var path = Path.Combine(_root, name);
        Directory.CreateDirectory(path);
        return path;
    }

    private SettingsLocation Where(string? app = null) => new()
    {
        GetEnv = n => _env.GetValueOrDefault(n),
        Home = Folder("home"),
        AppFolder = app ?? Folder("app"),
    };

    private string WriteLocal(SettingsLocation where, string json)
    {
        var folder = Path.Combine(where.AppFolder!, "config.local");
        Directory.CreateDirectory(folder);
        var file = Path.Combine(folder, SettingsLocation.FileName);
        File.WriteAllText(file, json);
        return file;
    }

    public void Dispose() => Directory.Delete(_root, recursive: true);

    [Fact]
    [Trait("Category", "Preserve")]
    public void Reads_disabled_agents_and_model_overrides_into_discovery_options()
    {
        var where = Where();
        var file = WriteLocal(where, """{"disabled_agents":["gemini",3,"cursor"],"models":{"opencode":["a/b","",7],"claude":[],"grok":"x"}}""");
        var result = AgentSettings.Load(where);
        Assert.Equal(file, result.Path);
        Assert.Null(result.Reason);
        Assert.Equal(["cursor", "gemini"], result.Options.Disabled.Order());
        Assert.Equal(["a/b"], result.Options.ModelOverrides["opencode"]);
        Assert.Empty(result.Options.ModelOverrides["claude"]);
        Assert.False(result.Options.ModelOverrides.ContainsKey("grok"));
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void The_options_reach_discovery_disabling_and_replacing_models()
    {
        var where = Where();
        WriteLocal(where, """{"disabled_agents":["gemini"],"models":{"claude":["only-one"]}}""");
        var options = AgentSettings.Load(where).Options with { ResolveBinary = c => "/bin/" + c, AppExists = _ => false };
        var found = AgentDiscovery.Discover(options);
        Assert.DoesNotContain(found, a => a.Command == "gemini");
        Assert.Equal(["only-one"], found.Single(a => a.Command == "claude").Models);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Missing_settings_give_the_defaults_without_a_reason()
    {
        var result = AgentSettings.Load(Where());
        Assert.Null(result.Path);
        Assert.Null(result.Reason);
        Assert.Empty(result.Options.Disabled);
        Assert.Empty(result.Options.ModelOverrides);
    }

    [Theory]
    [InlineData("not json {")]
    [InlineData("[1,2]")]
    [InlineData("")]
    [InlineData("""{"a":1,"a":2}""")]
    public void A_malformed_file_falls_back_to_the_defaults_with_a_reason(string text)
    {
        var where = Where();
        var file = WriteLocal(where, text);
        var result = AgentSettings.Load(where);
        Assert.Equal(file, result.Path);
        Assert.False(string.IsNullOrEmpty(result.Reason));
        Assert.Empty(result.Options.Disabled);
    }

    [Fact]
    public void A_directory_in_place_of_the_file_never_crashes()
    {
        var where = Where();
        Directory.CreateDirectory(Path.Combine(where.AppFolder!, "config.local", SettingsLocation.FileName));
        Assert.Empty(AgentSettings.Load(where).Options.Disabled);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void The_home_file_is_the_fallback_when_config_local_has_none()
    {
        var where = Where();
        var home = Path.Combine(where.Home!, ".agent_cli_bridge.json");
        File.WriteAllText(home, """{"disabled_agents":["grok"]}""");
        Assert.Equal(home, AgentSettings.Load(where).Path);
        Assert.Contains("grok", AgentSettings.Load(where).Options.Disabled);
        // a config.local file, once present, wins
        WriteLocal(where, """{"disabled_agents":["copilot"]}""");
        Assert.Equal(["copilot"], AgentSettings.Load(where).Options.Disabled);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void The_environment_names_the_folder_and_none_or_empty_means_this_computer_only()
    {
        var where = Where();
        var other = Folder("other");
        File.WriteAllText(Path.Combine(other, SettingsLocation.FileName), """{"disabled_agents":["opencode"]}""");
        WriteLocal(where, """{"disabled_agents":["copilot"]}""");
        _env[SettingsLocation.ConfigLocalEnv] = other;
        Assert.Equal(["opencode"], AgentSettings.Load(where).Options.Disabled);
        foreach (var off in new[] { "none", "  ", "" })
        {
            _env[SettingsLocation.ConfigLocalEnv] = off;
            Assert.Null(where.ConfigLocalDir());
            Assert.Empty(AgentSettings.Load(where).Options.Disabled);
        }
        _env[SettingsLocation.ConfigLocalEnv] = "~/cfg";
        Assert.Equal(Path.Combine(where.Home!, "cfg"), where.ConfigLocalDir());
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public void Enabling_an_agent_drops_it_and_keeps_the_rest_of_the_file()
    {
        var where = Where();
        var file = WriteLocal(where, """{"disabled_agents":["gemini","cursor"],"models":{"claude":["x"]},"other":true}""");
        AgentSettings.EnableAgents(new HashSet<string> { "gemini" }, where);
        var result = AgentSettings.Load(where);
        Assert.Equal(["cursor"], result.Options.Disabled);
        Assert.Equal(["x"], result.Options.ModelOverrides["claude"]);
        Assert.Contains("\"other\": true", File.ReadAllText(file));
        Assert.Empty(Directory.GetFiles(Path.GetDirectoryName(file)!, ".*.tmp"));
    }

    [Fact]
    public void Enabling_writes_nothing_when_none_is_listed_or_the_file_is_unusable()
    {
        var where = Where();
        var file = WriteLocal(where, """{"disabled_agents":["gemini"]}""");
        var before = File.GetLastWriteTimeUtc(file);
        AgentSettings.EnableAgents(new HashSet<string> { "grok" }, where);
        Assert.Equal("""{"disabled_agents":["gemini"]}""", File.ReadAllText(file));
        Assert.Equal(before, File.GetLastWriteTimeUtc(file));
        File.WriteAllText(file, "broken");
        AgentSettings.EnableAgents(new HashSet<string> { "gemini" }, where);
        Assert.Equal("broken", File.ReadAllText(file));
        AgentSettings.EnableAgents(new HashSet<string> { "gemini" }, Where(Folder("empty-app")));
    }

    // legacy apps-config migration — remove after 2027-01
    [Fact]
    [Trait("Category", "Preserve")]
    public void The_legacy_settings_are_copied_into_config_local_once_and_never_overwritten()
    {
        var where = Where();
        var apps = Folder("apps");
        Directory.CreateDirectory(Path.Combine(apps, "AgentCliBridge"));
        File.WriteAllText(Path.Combine(apps, "AgentCliBridge", SettingsLocation.FileName), """{"disabled_agents":["grok"]}""");
        _env["APPS_CONFIG_DIR"] = apps;
        var result = AgentSettings.Load(where);
        Assert.Equal(["grok"], result.Options.Disabled);
        Assert.Equal(Path.Combine(where.AppFolder!, "config.local", SettingsLocation.FileName), result.Path);
        Assert.Empty(Directory.GetFiles(Path.Combine(where.AppFolder!, "config.local"), "*.migrating"));
        // an existing file is left alone
        Assert.Null(LegacyMigration.Migrate(where, Path.Combine(where.AppFolder!, "config.local")));
    }

    [Fact]
    public void The_legacy_folder_comes_from_the_home_pointer_file_and_none_disables_it()
    {
        var where = Where();
        var apps = Folder("apps2");
        Directory.CreateDirectory(Path.Combine(apps, "AgentCliBridge"));
        File.WriteAllText(Path.Combine(where.Home!, ".apps-config-dir"), apps + "\nignored\n");
        Assert.Equal(Path.Combine(apps, "AgentCliBridge"), LegacyMigration.AppsConfigDir(where));
        _env["APPS_CONFIG_DIR"] = "none";
        Assert.Null(LegacyMigration.AppsConfigDir(where));
        _env["APPS_CONFIG_DIR"] = Path.Combine(_root, "missing");
        Assert.Null(LegacyMigration.AppsConfigDir(where));
    }
}
