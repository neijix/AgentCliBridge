using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

public class SignInErrorsTests
{
    private const string Cursor = "Error: Authentication required. Please run 'agent login' first, or set CURSOR_API_KEY environment variable.";
    private const string OAuth = "Failed to authenticate: OAuth session expired and could not be refreshed";

    [Fact]
    [Trait("Preserve", "P54")]
    public void A_signed_out_error_offers_to_sign_that_cli_in_and_nothing_else_does()
    {
        Assert.Equal("cursor-agent", SignInErrors.CommandFor(Cursor, "cursor-agent", ["claude", "cursor-agent"]));
        Assert.Equal("agent", SignInErrors.CommandFor(Cursor, "agent", ["agent"]));
        // A live error carries no agent: the machine's Cursor CLI is the one.
        Assert.Equal("agent", SignInErrors.CommandFor(Cursor, null, ["claude", "agent"]));
        Assert.Equal("cursor-agent", SignInErrors.CommandFor(Cursor, "cursor-agent", ["claude"]));
        Assert.Equal("", SignInErrors.CommandFor("rate limited", "cursor-agent", ["cursor-agent"]));
        Assert.Equal("", SignInErrors.CommandFor("", "cursor-agent", ["cursor-agent"]));
        Assert.Equal("claude", SignInErrors.CommandFor(OAuth, "claude", ["claude", "cursor-agent"]));
        Assert.Equal("claude", SignInErrors.CommandFor("Login expired · Please run /login", "claude", ["claude"]));
        Assert.Equal("claude", SignInErrors.CommandFor(OAuth, "claude", ["cursor-agent"]));
        Assert.Equal("claude", SignInErrors.CommandFor(OAuth, "claude", []));
        Assert.Equal("grok", SignInErrors.CommandFor("You are not authenticated. Run `grok login`.", "grok", ["grok", "claude"]));
        Assert.Equal("opencode", SignInErrors.CommandFor("No auth credentials found", "opencode", ["opencode"]));
        Assert.Equal("", SignInErrors.CommandFor("rate limited", "grok", ["grok"]));
        Assert.Equal("copilot", SignInErrors.CommandFor("Error: No authentication information found.", "copilot", ["copilot"]));
    }

    [Fact]
    [Trait("Preserve", "P54")]
    public void A_long_reply_that_merely_quotes_the_phrase_is_not_a_sign_in_error()
        => Assert.Equal("", SignInErrors.CommandFor($"{OAuth}\n\n{new string('x', 500)}", "claude", ["claude"]));

    [Fact]
    [Trait("Preserve", "P54")]
    public void The_text_is_the_content_or_else_the_text_parts()
    {
        Assert.Equal(OAuth, SignInErrors.TextFrom(OAuth));
        Assert.Equal(OAuth, SignInErrors.TextFrom("", [("text", OAuth)]));
        Assert.Equal("", SignInErrors.TextFrom(null, [("thinking", "x")]));
    }

    [Fact]
    [Trait("Preserve", "P54")]
    public void Every_cli_that_can_sign_in_has_an_error_that_names_it()
    {
        foreach (var command in new[] { "claude", "agent", "cursor-agent", "grok", "opencode", "copilot" })
        {
            Assert.True(LoginSpecs.CanSignIn(command));
        }
        Assert.False(LoginSpecs.CanSignIn("gemini"));
        Assert.False(LoginSpecs.CanSignIn("agy"));
    }
}
