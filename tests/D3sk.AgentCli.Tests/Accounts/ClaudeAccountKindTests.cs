using System.Text.Json;
using D3sk.AgentCli.Accounts;

namespace D3sk.AgentCli.Tests.Accounts;

public sealed class ClaudeAccountKindTests : IDisposable
{
    private readonly string _tmp = Path.Combine(Path.GetTempPath(), "ak-" + Guid.NewGuid().ToString("N"));

    public ClaudeAccountKindTests() => Directory.CreateDirectory(_tmp);

    public void Dispose() => Directory.Delete(_tmp, true);

    private static Dictionary<string, string> Env(params (string, string)[] pairs) =>
        pairs.ToDictionary(p => p.Item1, p => p.Item2);

    private string Home(Dictionary<string, string>? settingsEnv = null, string? organization = null, string? name = null)
    {
        var home = Path.Combine(_tmp, name ?? Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(home, ".claude"));
        if (settingsEnv is not null)
        {
            File.WriteAllText(Path.Combine(home, ".claude", "settings.json"), JsonSerializer.Serialize(new { env = settingsEnv }));
        }
        if (organization is not null)
        {
            SignIn(home, organization);
        }
        return home;
    }

    private static void SignIn(string dir, string organization, string uuid = "u1") =>
        File.WriteAllText(Path.Combine(dir, ".claude.json"),
            JsonSerializer.Serialize(new { oauthAccount = new { accountUuid = uuid, organizationType = organization } }));

    private static void Is(string kind, string detail, ClaudeAccount? actual)
    {
        Assert.NotNull(actual);
        Assert.Equal(kind, actual.Kind);
        Assert.Equal(detail, actual.Detail);
    }

    private void Write(string home, string json) => File.WriteAllText(Path.Combine(home, ".claude.json"), json);

    [Fact]
    public void A_company_gateway_in_the_environment_is_the_work_account()
    {
        var home = Home(organization: "claude_max");
        Is("work", "127.0.0.1:4000", ClaudeAccountKind.Of(home, Env(("ANTHROPIC_BASE_URL", "http://127.0.0.1:4000"))));
    }

    [Fact]
    public void A_gateway_in_claude_settings_counts_too()
    {
        var home = Home(Env(("ANTHROPIC_BASE_URL", "https://ai.example.com/anthropic")));
        Is("work", "ai.example.com", ClaudeAccountKind.Of(home, Env()));
    }

    [Fact]
    public void Anthropics_own_api_url_is_not_a_gateway()
    {
        var home = Home(organization: "claude_max");
        Is("personal", "Max", ClaudeAccountKind.Of(home, Env(("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))));
        Is("personal", "Max", ClaudeAccountKind.Of(home, Env(("ANTHROPIC_BASE_URL", "https://anthropic.com"))));
    }

    [Fact]
    public void A_cloud_provider_is_the_work_account_and_the_first_switch_wins()
    {
        Is("work", "Bedrock", ClaudeAccountKind.Of(_tmp, Env(("CLAUDE_CODE_USE_BEDROCK", "1"))));
        Assert.Null(ClaudeAccountKind.Of(_tmp, Env(("CLAUDE_CODE_USE_VERTEX", "0"))));
        Is("work", "Bedrock", ClaudeAccountKind.Of(_tmp,
            Env(("CLAUDE_CODE_USE_FOUNDRY", "1"), ("CLAUDE_CODE_USE_VERTEX", "1"), ("CLAUDE_CODE_USE_BEDROCK", "1"))));
        Is("work", "Vertex", ClaudeAccountKind.Of(_tmp,
            Env(("CLAUDE_CODE_USE_FOUNDRY", "1"), ("CLAUDE_CODE_USE_VERTEX", "1"), ("ANTHROPIC_BASE_URL", "https://gw.example"))));
        Is("work", "Foundry", ClaudeAccountKind.Of(_tmp, Env(("CLAUDE_CODE_USE_FOUNDRY", "true"))));
    }

    [Fact]
    public void A_claude_ai_sign_in_is_personal_unless_its_organization_is_a_company()
    {
        var home = Home(organization: "claude_pro");
        Is("personal", "Pro", ClaudeAccountKind.Of(home, Env()));
        SignIn(home, "claude_enterprise");
        Is("work", "Enterprise", ClaudeAccountKind.Of(home, Env()));
        SignIn(home, "claude_team");
        Is("work", "Team", ClaudeAccountKind.Of(home, Env()));
        SignIn(home, "claude_free");
        Is("personal", "Free", ClaudeAccountKind.Of(home, Env()));
        SignIn(home, "claude_max");
        Is("personal", "Max", ClaudeAccountKind.Of(home, Env()));
        SignIn(home, "something_else");
        Is("personal", "claude.ai", ClaudeAccountKind.Of(home, Env()));
    }

    [Fact]
    public void No_sign_in_and_no_gateway_gives_no_tag()
    {
        var home = Home();
        Assert.Null(ClaudeAccountKind.Of(home, Env()));
        foreach (var json in new[]
        {
            "not json", "[1]", "{\"oauthAccount\":{\"organizationType\":\"claude_pro\"}}",
            "{\"oauthAccount\":{\"accountUuid\":\"\",\"organizationType\":\"claude_pro\"}}", "{\"oauthAccount\":\"x\"}",
        })
        {
            Write(home, json);
            Assert.Null(ClaudeAccountKind.Of(home, Env()));
        }
    }

    [Fact]
    public void A_port_that_is_not_a_number_is_no_gateway_and_no_crash()
    {
        Assert.Null(ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "http://127.0.0.1:port"))));
    }

    [Fact]
    public void The_detail_names_the_host_in_lower_case_and_the_port_the_url_names()
    {
        Is("work", "gw.example.com", ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "https://GW.Example.com/x"))));
        Is("work", "gw.example.com:443", ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "https://gw.example.com:443"))));
        Is("work", "gw.example.com:8443", ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "https://user:pw@gw.example.com:8443/p"))));
    }

    [Fact]
    public void Any_scheme_counts_as_python_does_but_a_url_without_a_host_does_not()
    {
        Is("work", "gw.example.com", ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "ftp://gw.example.com"))));
        Assert.Null(ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "gw.example.com:443"))));
        Assert.Null(ClaudeAccountKind.Of(_tmp, Env(("ANTHROPIC_BASE_URL", "   "))));
    }

    [Fact]
    public void The_account_follows_claude_config_dir()
    {
        var profile = Path.Combine(_tmp, "profile");
        Directory.CreateDirectory(profile);
        File.WriteAllText(Path.Combine(profile, "settings.json"),
            JsonSerializer.Serialize(new { env = new { ANTHROPIC_BASE_URL = "https://gw.example" } }));
        var home = Home(organization: "claude_max", name: "home");
        var env = Env(("CLAUDE_CONFIG_DIR", profile));
        Is("work", "gw.example", ClaudeAccountKind.Of(home, env));
        File.WriteAllText(Path.Combine(profile, "settings.json"), "{}");
        SignIn(profile, "claude_pro", "u2");
        Is("personal", "Pro", ClaudeAccountKind.Of(home, env));
    }
}
