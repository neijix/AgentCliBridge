using System.Text.Json;
using D3sk.AgentCli.Accounts;

namespace D3sk.AgentCli.Tests.Accounts;

public sealed class ClaudeGatewayTests : IDisposable
{
    private readonly string _tmp = Path.Combine(Path.GetTempPath(), "gw-" + Guid.NewGuid().ToString("N"));

    public ClaudeGatewayTests() => Directory.CreateDirectory(_tmp);

    public void Dispose() => Directory.Delete(_tmp, true);

    private static Dictionary<string, string> Env(params (string, string)[] pairs) =>
        pairs.ToDictionary(p => p.Item1, p => p.Item2);

    private string Home(Dictionary<string, string>? settingsEnv = null)
    {
        var home = Path.Combine(_tmp, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(home, ".claude"));
        if (settingsEnv is not null)
        {
            File.WriteAllText(Path.Combine(home, ".claude", "settings.json"), JsonSerializer.Serialize(new { env = settingsEnv }));
        }
        return home;
    }

    private static string[][] Pairs(GatewayHeaders h) => h.Select(p => new[] { p.Key, p.Value }).ToArray();

    private static GatewayHeaders HeadersOf(string home, string custom) =>
        ClaudeGateway.Headers(home, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_CUSTOM_HEADERS", custom)));

    [Fact]
    public void The_gateway_is_the_base_url_claude_code_talks_to()
    {
        Assert.Equal("http://127.0.0.1:4000", ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", " http://127.0.0.1:4000 "))));
        var home = Home(Env(("ANTHROPIC_BASE_URL", "https://ai.example.com/anthropic")));
        Assert.Equal("https://ai.example.com/anthropic", ClaudeGateway.Url(home, Env(("ANTHROPIC_BASE_URL", "http://127.0.0.1:4000"))));
    }

    [Fact]
    public void Anthropic_a_cloud_provider_or_a_url_that_is_not_http_has_no_gateway()
    {
        Assert.Null(ClaudeGateway.Url(_tmp, Env()));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "https://anthropic.com"))));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "http://127.0.0.1:4000"), ("CLAUDE_CODE_USE_BEDROCK", "1"))));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "file:///etc/hosts"))));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "ftp://files.example.com"))));
        Assert.Null(ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "http://127.0.0.1:port"))));
    }

    [Theory]
    [InlineData("CLAUDE_CODE_USE_VERTEX", " YES ", true)]
    [InlineData("CLAUDE_CODE_USE_FOUNDRY", "true", true)]
    [InlineData("CLAUDE_CODE_USE_BEDROCK", "0", false)]
    [InlineData("CLAUDE_CODE_USE_BEDROCK", " Off ", false)]
    [InlineData("CLAUDE_CODE_USE_BEDROCK", "", false)]
    [InlineData("CLAUDE_CODE_USE_BEDROCK", "No", false)]
    [InlineData("CLAUDE_CODE_USE_BEDROCK", "FALSE", false)]
    public void A_cloud_switch_is_on_for_anything_but_empty_0_false_no_off(string name, string value, bool on)
    {
        var url = ClaudeGateway.Url(_tmp, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), (name, value)));
        Assert.Equal(on ? null : "https://ai.example.com", url);
    }

    [Fact]
    public void The_gateway_gets_the_credentials_claude_code_sends_it()
    {
        var env = Env(
            ("ANTHROPIC_BASE_URL", "https://ai.example.com/ai-gateway/anthropic"),
            ("ANTHROPIC_AUTH_TOKEN", " dapi-token "),
            ("ANTHROPIC_API_KEY", "sk-key"),
            ("ANTHROPIC_CUSTOM_HEADERS", "x-team-mode: true\nbad header: x\nno-colon\nx-empty:\n"));
        Assert.Equal(
            [["x-team-mode", "true"], ["x-api-key", "sk-key"], ["Authorization", "Bearer dapi-token"]],
            Pairs(ClaudeGateway.Headers(_tmp, env)));
        var home = Home(Env(("ANTHROPIC_AUTH_TOKEN", "from-settings")));
        Assert.Equal("Bearer from-settings", ClaudeGateway.Headers(home, env)["Authorization"]);
    }

    [Fact]
    public void No_gateway_means_no_credentials_are_handed_out()
    {
        var token = new[] { ("ANTHROPIC_AUTH_TOKEN", "secret"), ("ANTHROPIC_API_KEY", "sk-key") };
        Assert.Empty(ClaudeGateway.Headers(_tmp, Env(token)));
        Assert.Empty(ClaudeGateway.Headers(_tmp, Env([.. token, ("ANTHROPIC_BASE_URL", "https://api.anthropic.com")])));
        Assert.Empty(ClaudeGateway.Headers(_tmp, Env([.. token, ("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("CLAUDE_CODE_USE_BEDROCK", "1")])));
        Assert.Empty(ClaudeGateway.Headers(_tmp, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_AUTH_TOKEN", "a\r\nX-Injected: 1"))));
        Assert.Empty(GatewayHeaders.Empty);
    }

    [Fact]
    public void Claude_config_dir_is_followed()
    {
        var profile = Path.Combine(_tmp, "profile");
        Directory.CreateDirectory(profile);
        File.WriteAllText(Path.Combine(profile, "settings.json"), """{"env":{"ANTHROPIC_BASE_URL":"https://gw.example.com","ANTHROPIC_AUTH_TOKEN":"p"}}""");
        var home = Home(Env(("ANTHROPIC_BASE_URL", "https://other.example.com")));
        var env = Env(("CLAUDE_CONFIG_DIR", profile));
        Assert.Equal("https://gw.example.com", ClaudeGateway.Url(home, env));
        Assert.Equal("Bearer p", ClaudeGateway.Headers(home, env)["Authorization"]);
    }

    [Theory]
    [InlineData("not json")]
    [InlineData("[1,2]")]
    [InlineData("""{"env":"x"}""")]
    [InlineData("""{"env":[1]}""")]
    public void A_malformed_or_non_object_settings_file_counts_as_no_settings_env(string content)
    {
        var home = Home();
        File.WriteAllText(Path.Combine(home, ".claude", "settings.json"), content);
        Assert.Equal("https://ai.example.com", ClaudeGateway.Url(home, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"))));
    }

    [Fact]
    public void An_unreadable_settings_file_counts_as_no_settings_env()
    {
        var home = Home();
        Directory.CreateDirectory(Path.Combine(home, ".claude", "settings.json"));
        Assert.Equal("https://ai.example.com", ClaudeGateway.Url(home, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"))));
    }

    [Fact]
    public void Only_string_values_of_the_settings_env_count()
    {
        var home = Home();
        File.WriteAllText(Path.Combine(home, ".claude", "settings.json"), """{"env":{"ANTHROPIC_BASE_URL":5,"ANTHROPIC_API_KEY":"k"}}""");
        Assert.Equal("https://ai.example.com", ClaudeGateway.Url(home, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"))));
        Assert.Equal("k", ClaudeGateway.Headers(home, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com")))["x-api-key"]);
    }

    [Fact]
    public void An_api_key_helper_adds_no_header_and_starts_no_process()
    {
        var marker = Path.Combine(_tmp, "ran.txt");
        var home = Home();
        File.WriteAllText(Path.Combine(home, ".claude", "settings.json"),
            JsonSerializer.Serialize(new { apiKeyHelper = $"echo x > \"{marker}\"", env = new { ANTHROPIC_BASE_URL = "https://ai.example.com" } }));
        Assert.Empty(ClaudeGateway.Headers(home, Env()));
        Assert.False(File.Exists(marker));
    }

    [Theory]
    [InlineData("\n")]
    [InlineData("\r")]
    [InlineData("\v")]
    [InlineData("\f")]
    [InlineData("\u001c")]
    [InlineData("\u001d")]
    [InlineData("\u001e")]
    [InlineData("\u0085")]
    [InlineData("\u2028")]
    [InlineData("\u2029")]
    public void Custom_header_lines_split_at_each_python_splitlines_separator(string separator)
    {
        Assert.Equal([["X-A", "1"], ["X-B", "2"]], Pairs(HeadersOf(_tmp, "X-A: 1" + separator + "X-B: 2")));
    }

    [Fact]
    public void A_crlf_is_one_separator()
    {
        Assert.Equal([["X-A", "1"], ["X-B", "2"]], Pairs(HeadersOf(_tmp, "X-A: 1\r\nX-B: 2")));
    }

    [Fact]
    public void A_line_is_split_at_its_first_colon_and_trimmed()
    {
        Assert.Equal([["X-A", "a: b"]], Pairs(HeadersOf(_tmp, "  X-A  :  a: b  ")));
    }

    [Theory]
    [InlineData("X A: 1")]
    [InlineData("X@A: 1")]
    [InlineData(": 1")]
    [InlineData("X-A:")]
    public void An_invalid_name_or_empty_value_is_dropped(string line) => Assert.Empty(HeadersOf(_tmp, line));

    [Fact]
    public void A_name_of_100_characters_is_kept_and_101_dropped()
    {
        Assert.Single(HeadersOf(_tmp, new string('a', 100) + ": 1"));
        Assert.Empty(HeadersOf(_tmp, new string('a', 101) + ": 1"));
    }

    [Fact]
    public void A_printable_non_ascii_value_and_an_inner_space_are_kept()
    {
        var value = "caf" + (char)0xE9 + " " + (char)0x4E2D + char.ConvertFromUtf32(0x1F600);
        Assert.Equal([["X-A", value]], Pairs(HeadersOf(_tmp, "X-A: " + value)));
    }

    [Theory]
    [InlineData(0x0001)] // Cc
    [InlineData(0x200B)] // Cf
    [InlineData(0xE000)] // Co
    [InlineData(0x0378)] // Cn
    [InlineData(0x00A0)] // Zs
    [InlineData(0x3000)] // Zs
    [InlineData(0xF0000)] // Co, outside the BMP
    public void A_value_with_a_non_printable_character_is_dropped(int codePoint)
    {
        var value = "a" + char.ConvertFromUtf32(codePoint) + "b";
        var env = Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_API_KEY", value), ("ANTHROPIC_AUTH_TOKEN", value));
        Assert.Empty(ClaudeGateway.Headers(_tmp, env));
        Assert.Empty(HeadersOf(_tmp, "X-A: " + value));
    }

    [Fact]
    public void A_lone_surrogate_is_not_printable()
    {
        foreach (var value in new[] { "a" + (char)0xD800 + "b", "a" + (char)0xDC00 + "b", "a" + (char)0xD800 })
        {
            var env = Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_API_KEY", value));
            Assert.Empty(ClaudeGateway.Headers(_tmp, env));
        }
    }

    [Fact]
    public void A_surrogate_pair_is_one_printable_character()
    {
        Assert.Single(ClaudeGateway.Headers(_tmp, Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_API_KEY", "k\U0001F600"))));
    }

    [Fact]
    public void A_key_or_token_that_is_blank_adds_nothing()
    {
        var env = Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_API_KEY", "  "), ("ANTHROPIC_AUTH_TOKEN", ""));
        Assert.Empty(ClaudeGateway.Headers(_tmp, env));
    }

    [Theory]
    [InlineData("authorization: custom", "Authorization", "Bearer tok")]
    [InlineData("AUTHORIZATION: custom", "Authorization", "Bearer tok")]
    [InlineData("X-API-KEY: custom", "x-api-key", "sk")]
    public void A_custom_header_of_the_same_name_is_replaced_not_doubled(string custom, string name, string value)
    {
        var env = Env(
            ("ANTHROPIC_BASE_URL", "https://ai.example.com"),
            ("ANTHROPIC_API_KEY", "sk"), ("ANTHROPIC_AUTH_TOKEN", "tok"),
            ("ANTHROPIC_CUSTOM_HEADERS", "X-First: 1\n" + custom + "\nX-Last: 2"));
        var headers = Pairs(ClaudeGateway.Headers(_tmp, env));
        Assert.Equal(4, headers.Length);
        Assert.Equal("X-First", headers[0][0]);
        Assert.Equal([name, value], headers[1]);
        Assert.Equal("X-Last", headers[2][0]);
    }

    [Fact]
    public void Names_compare_case_insensitively_and_the_later_spelling_wins_at_the_first_position()
    {
        var env = Env(("ANTHROPIC_BASE_URL", "https://ai.example.com"), ("ANTHROPIC_CUSTOM_HEADERS", "x-a: 1\nX-B: 2\nX-A: 3"));
        var headers = ClaudeGateway.Headers(_tmp, env);
        Assert.Equal([["X-A", "3"], ["X-B", "2"]], Pairs(headers));
        Assert.Equal("3", headers["x-a"]);
        Assert.True(headers.ContainsKey("x-b"));
        Assert.False(headers.ContainsKey("x-c"));
        Assert.Throws<KeyNotFoundException>(() => headers["x-c"]);
    }
}
