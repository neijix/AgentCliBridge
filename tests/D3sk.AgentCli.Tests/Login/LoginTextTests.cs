using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

public class LoginTextTests
{
    private const string Link = "https://cursor.com/loginDeepControl?challenge=abc&uuid=1&mode=login&redirectTarget=cli";
    private const string ClaudeLink = "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a&response_type=code";
    private const string GrokLink = "https://auth.x.ai/activate?user_code=WDRA-TKXP";
    private const string CopilotPage = "https://github.com/login/device";

    [Fact]
    [Trait("Category", "Security")]
    [Trait("Preserve", "P38")]
    public void Only_a_link_on_the_cli_s_own_host_is_handed_to_the_browser()
    {
        string[] cursor = ["cursor.com"];
        Assert.Equal(Link, LoginText.Link($"navigate to this link: {Link}", cursor));
        Assert.Equal("", LoginText.Link("go to https://evil.example/cursor.com/login", cursor));
        Assert.Equal("", LoginText.Link("go to http://cursor.com/login", cursor));
        Assert.Equal("", LoginText.Link("go to https://cursor.com.evil.example/login", cursor));
        Assert.Equal("", LoginText.Link("go to https://cursor.com@evil.example/login", cursor));
        Assert.Equal(ClaudeLink, LoginText.Link($"visit: {ClaudeLink}", ["claude.com"]));
        Assert.Equal("", LoginText.Link($"visit: {ClaudeLink}", cursor));
        Assert.Equal(GrokLink, LoginText.Link($"open {GrokLink}", ["auth.x.ai"]));
        Assert.Equal("https://openrouter.ai/keys", LoginText.Link("https://openrouter.ai/keys", ["openrouter.ai"]));
        Assert.Equal(CopilotPage, LoginText.Link($"visit {CopilotPage} and enter", ["github.com"]));
        Assert.Equal("", LoginText.Link("visit https://github.com.evil.example/login/device", ["github.com"]));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void The_device_code_comes_from_the_link_or_the_text()
    {
        Assert.Equal("WDRA-TKXP", LoginText.UserCode(GrokLink));
        Assert.Equal("ABCD-1234", LoginText.UserCode("Make sure your browser shows this code: ABCD-1234"));
        Assert.Equal("", LoginText.UserCode("no code here"));
        Assert.Equal("92EC-55BB", LoginText.UserCode($"To authenticate, visit {CopilotPage} and enter code 92EC-55BB"));
        Assert.Equal("", LoginText.UserCode("enter code here"));
    }

    [Theory]
    [Trait("Preserve", "P38")]
    [InlineData(0, "Not logged in", false)]
    [InlineData(1, "Error: Authentication required. Please run 'agent login'", false)]
    [InlineData(0, "✓ Logged in as owner@example.com", true)]
    [InlineData(0, "something else", null)]
    [InlineData(1, "{\"loggedIn\": false, \"authMethod\": \"none\"}", false)]
    [InlineData(0, "{\"loggedIn\": true, \"authMethod\": \"claude.ai\"}", true)]
    [InlineData(0, "You are logged in with grok.com.", true)]
    [InlineData(0, "You are not authenticated.", false)]
    [InlineData(0, "OpenRouter api\n1 credentials", true)]
    [InlineData(0, "0 credentials", false)]
    [InlineData(0, "OpenRouter api\n0 credentials", false)]
    [InlineData(0, "●  OpenRouter \u001b[90mapi\n└  1 credentials\n\u001b[0m\n", true)]
    [InlineData(0, "Error: no OpenRouter key found", null)]
    [InlineData(0, "Add credential for openrouter? (y/N)", null)]
    [InlineData(0, "OpenRouter api key is invalid", null)]
    [InlineData(0, "┌  Credentials\n│\n●  OpenRouter oauth\n│\n└  1 credentials", true)]
    public void Status_output_reads_as_signed_in_signed_out_or_unknown(int code, string output, bool? expected)
        => Assert.Equal(expected, LoginText.ParseSignedIn(code, output));

    [Fact]
    [Trait("Category", "Security")]
    [Trait("Preserve", "P38")]
    public void Shown_output_redacts_bearer_tokens_and_api_keys()
    {
        // Built by concatenation so no source line looks like a real credential.
        var sk = "sk-" + "proj12345678";
        var openrouter = "sk-or-v1-" + "deadbeefcafebabe";
        var bearer = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "dozjgNryP4J3jVmNHl0w5N";
        var labeled = "plainkeyvalue123456";
        var spaced = "spacedsecretvalue99";
        var header = "notsksecretvalue1";
        var github = "ghp" + "_" + new string('b', 36);
        var fine = "github" + "_pat_" + new string('c', 22);
        var text = $"before Authorization: Bearer {bearer} api_key={labeled} API key: {spaced} x-api-key: {header} "
            + $"{github} {fine} {sk} {openrouter} after WDRA-TKXP browser=1";
        var shown = LoginText.Tail(text);
        foreach (var secret in new[] { sk, openrouter, bearer, "eyJzdWIiOiIxMjM0NTY3ODkwIn0", labeled, spaced, header, github, fine })
        {
            Assert.DoesNotContain(secret, shown);
        }
        Assert.Contains("[redacted]", shown);
        Assert.Contains("before", shown);
        Assert.Contains("after", shown);
        Assert.Contains("WDRA-TKXP", shown);
        Assert.Contains("browser=1", shown);
        var xai = "xai-" + "AbCdEf0123456789xyz";
        var shownXai = LoginText.Tail($"before {xai} after XAI_KEY=xai-short");
        Assert.DoesNotContain(xai, shownXai);
        Assert.Contains("xai-short", shownXai);
    }

    [Fact]
    public void Only_the_last_4000_characters_are_shown()
        => Assert.Equal(LoginText.OutputTail, LoginText.Tail(new string('x', 9000)).Length);
}
