using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

public class CliLoginsTests
{
    private const string Link = "https://cursor.com/loginDeepControl?challenge=abc&uuid=1&mode=login&redirectTarget=cli";
    private const string ClaudeLink = "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a&response_type=code";
    private const string GrokLink = "https://auth.x.ai/activate?user_code=WDRA-TKXP";
    private static readonly LoginTimings Quick = new() { LinkWait = TimeSpan.FromSeconds(5), StopGrace = TimeSpan.FromMilliseconds(10) };

    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task Login_runs_without_a_browser_returns_its_link_and_reports_the_sign_in()
    {
        var host = new FakeLoginHost { LoginLines = ["Starting login process...", $"Open a browser and navigate to this link: {Link}"] };
        var signedIn = false;
        host.Answer = _ => new LoginCommandResult(0, signedIn ? "Logged in as owner@example.com" : "Not logged in", "");
        var logins = new CliLogins(host, timings: Quick);

        var started = await logins.StartAsync("cursor-agent", "/bin/cursor-agent", Ct);
        Assert.Equal(Link, started.Url);
        Assert.True(started.Running);
        Assert.Equal("1", host.LastEnv["NO_OPEN_BROWSER"]); // the host never opens a browser itself
        Assert.Equal(["login"], host.Started[0].Argv.Skip(1));
        // Asking again reuses the login still waiting instead of starting a second one.
        Assert.Equal(Link, (await logins.StartAsync("cursor-agent", "/bin/cursor-agent", Ct)).Url);
        Assert.Single(host.Started);

        var status = await logins.StatusAsync("cursor-agent", "/bin/cursor-agent", Ct);
        Assert.False(status.SignedIn);
        Assert.True(status.Running);
        Assert.Equal(Link, status.Url);
        signedIn = true;
        Assert.True((await logins.StatusAsync("cursor-agent", "/bin/cursor-agent", Ct)).SignedIn);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task Claude_login_returns_its_link_and_takes_the_pasted_code()
    {
        var host = new FakeLoginHost { LoginLines = ["Opening browser to sign in…", $"If the browser didn't open, visit: {ClaudeLink}"] };
        host.Answer = _ => new LoginCommandResult(0, "{\"loggedIn\": false}", "");
        var logins = new CliLogins(host, timings: Quick);

        var started = await logins.StartAsync("claude", "/bin/claude", Ct);
        Assert.Equal(ClaudeLink, started.Url);
        Assert.True(started.Running && started.NeedsCode);
        Assert.Equal(["auth", "login", "--claudeai"], host.Started[0].Argv.Skip(1));
        Assert.Equal("true", host.LastEnv["BROWSER"]);
        var status = await logins.StatusAsync("claude", "/bin/claude", Ct);
        Assert.False(status.SignedIn);
        Assert.True(status.NeedsCode);

        await Assert.ThrowsAsync<LoginException>(() => logins.SubmitAsync("cursor-agent", "GOODCODE", Ct));
        await logins.SubmitAsync("claude", "  GOODCODE ", Ct);
        Assert.Equal(["GOODCODE\n\n"], host.Started[0].Written);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task Grok_device_auth_returns_its_link_and_the_code_to_type_and_logs_out()
    {
        var host = new FakeLoginHost
        {
            LoginLines = ["To sign in, open this URL in your browser:", GrokLink, "Make sure your browser shows this code: WDRA-TKXP"],
        };
        var signedIn = false;
        host.Answer = argv => argv[1] == "logout"
            ? Logout()
            : new LoginCommandResult(0, signedIn ? "You are logged in with grok.com." : "You are not authenticated.", "");
        LoginCommandResult Logout()
        {
            signedIn = false;
            return new LoginCommandResult(0, "Logged out", "");
        }
        var logins = new CliLogins(host, timings: Quick);

        var started = await logins.StartAsync("grok", "/bin/grok", Ct);
        Assert.Equal(GrokLink, started.Url);
        Assert.False(started.NeedsCode);
        Assert.Equal("WDRA-TKXP", started.UserCode);
        Assert.Equal("WDRA-TKXP", (await logins.StatusAsync("grok", "/bin/grok", Ct)).UserCode);
        signedIn = true;
        Assert.True((await logins.StatusAsync("grok", "/bin/grok", Ct)).SignedIn);
        var out_ = await logins.LogoutAsync("grok", "/bin/grok", Ct);
        Assert.False(out_.SignedIn);
        Assert.Contains("terminate", host.Started[0].Calls); // the waiting login was ended first
        Assert.Contains("Logged out", out_.Output);
    }

    [Fact]
    [Trait("Category", "Security")]
    [Trait("Preserve", "P38")]
    public async Task Opencode_opens_the_keys_page_stores_a_pasted_key_and_never_shows_it()
    {
        var key = "sk-or-v1-" + "deadbeefcafebabe";
        var host = new FakeLoginHost { LoginLines = ["Enter your API key"] };
        host.Answer = _ => new LoginCommandResult(0, "OpenRouter api\n1 credentials", "");
        var logins = new CliLogins(host, timings: Quick);

        var started = await logins.StartAsync("opencode", "/bin/opencode", Ct);
        Assert.Equal("https://openrouter.ai/keys", started.Url);
        Assert.True(started.Running && started.NeedsCode);
        await Assert.ThrowsAsync<LoginException>(() => logins.SubmitAsync("opencode", "", Ct));
        await logins.SubmitAsync("opencode", key, Ct);
        Assert.Equal([key + "\r\n"], host.Started[0].Written);
        host.Started[0].Print($"got {key}");
        await Task.Delay(100, Ct);
        var status = await logins.StatusAsync("opencode", "/bin/opencode", Ct);
        Assert.True(status.SignedIn);
        Assert.DoesNotContain(key, status.Output);
        Assert.Contains("[redacted]", status.Output);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task A_paste_that_is_empty_has_a_newline_or_is_too_long_never_reaches_the_cli()
    {
        var host = new FakeLoginHost { LoginLines = ["Enter your API key"] };
        var logins = new CliLogins(host, timings: Quick);
        await logins.StartAsync("opencode", "/bin/opencode", Ct);
        foreach (var pasted in new[] { "", " \t ", "has\ninside", "has\rinside", new string('x', CliLogins.CodeMax + 1) })
        {
            var e = await Assert.ThrowsAsync<LoginException>(() => logins.SubmitAsync("opencode", pasted, Ct));
            Assert.Contains("Paste the code", e.Message);
        }
        Assert.Empty(host.Started[0].Written);
        await logins.SubmitAsync("opencode", new string('y', CliLogins.CodeMax), Ct); // at the limit it goes through
        Assert.Single(host.Started[0].Written);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task A_paste_with_no_sign_in_waiting_is_refused()
    {
        var logins = new CliLogins(new FakeLoginHost(), timings: Quick);
        var e = await Assert.ThrowsAsync<LoginException>(() => logins.SubmitAsync("claude", "y", Ct));
        Assert.Contains("No sign-in is waiting", e.Message);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task A_login_that_prints_a_foreign_link_is_refused_and_stopped()
    {
        var host = new FakeLoginHost { LoginLines = ["Open https://evil.example/login"] };
        var logins = new CliLogins(host, timings: new LoginTimings { LinkWait = TimeSpan.FromMilliseconds(300), StopGrace = TimeSpan.FromMilliseconds(10) });
        var e = await Assert.ThrowsAsync<LoginException>(() => logins.StartAsync("cursor-agent", "/bin/cursor-agent", Ct));
        Assert.Contains("no sign-in link", e.Message);
        Assert.True(host.Started[0].HasExited); // the waiting CLI was terminated, not left behind
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task Only_known_clis_can_be_signed_in_and_never_from_a_request_argv()
    {
        var logins = new CliLogins(new FakeLoginHost(), timings: Quick);
        var e = await Assert.ThrowsAsync<LoginException>(() => logins.StartAsync("rm", "/bin/rm", Ct));
        Assert.Contains("cannot sign", e.Message);
        await Assert.ThrowsAsync<LoginException>(() => logins.StartAsync("gemini", "/bin/gemini", Ct));
        await Assert.ThrowsAsync<LoginException>(() => logins.StartAsync("claude", "", Ct));
        Assert.True(LoginSpecs.NeedsCode("claude") && LoginSpecs.NeedsCode("opencode"));
        Assert.False(LoginSpecs.NeedsCode("cursor-agent") || LoginSpecs.NeedsCode("grok") || LoginSpecs.NeedsCode("copilot"));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task A_sign_in_clears_quarantine_before_the_cli_starts()
    {
        var host = new FakeLoginHost { LoginLines = [Link] };
        await new CliLogins(host, timings: Quick).StartAsync("cursor-agent", "/bin/cursor-agent", Ct);
        Assert.Equal(["clear:/bin/cursor-agent", "start"], host.Events.Take(2));
    }

    [Fact]
    [Trait("Category", "Security")]
    [Trait("Preserve", "P38")]
    public async Task A_login_that_ignores_terminate_is_killed_and_collected()
    {
        var host = new FakeLoginHost { Stubborn = true, LoginLines = [Link] };
        var logins = new CliLogins(host, timings: Quick);
        await logins.StartAsync("cursor-agent", "/bin/cursor-agent", Ct);
        await logins.LogoutAsync("cursor-agent", "/bin/cursor-agent", Ct);
        var calls = host.Started[0].Calls;
        Assert.Equal("terminate", calls[0]);
        Assert.True(calls.IndexOf("kill") > 0);
        Assert.Equal("wait", calls[^1]);
        Assert.True(host.Started[0].HasExited);

        var polite = new FakeLoginHost { LoginLines = [Link] };
        var other = new CliLogins(polite, timings: Quick);
        await other.StartAsync("cursor-agent", "/bin/cursor-agent", Ct);
        await other.StopAllAsync();
        Assert.Equal(["terminate", "wait"], polite.Started[0].Calls);
    }

    [Fact]
    [Trait("Category", "Security")]
    public async Task Every_expired_login_is_swept_not_only_the_one_asked_about()
    {
        var time = new ManualTime();
        var host = new FakeLoginHost { LoginLines = [ClaudeLink] };
        var logins = new CliLogins(host, time, Quick);
        await logins.StartAsync("claude", "/bin/claude", Ct);
        time.Advance(TimeSpan.FromMinutes(9));
        await logins.StartAsync("opencode", "/bin/opencode", Ct);
        time.Advance(TimeSpan.FromMinutes(2));

        await logins.StatusAsync("opencode", "/bin/opencode", Ct); // asks about opencode; claude's login is ended too
        Assert.Contains("terminate", host.Started[0].Calls);
        Assert.DoesNotContain("terminate", host.Started[1].Calls);
        var e = await Assert.ThrowsAsync<LoginException>(() => logins.SubmitAsync("claude", "x", Ct));
        Assert.Contains("No sign-in is waiting", e.Message);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task Copilot_signs_in_with_a_device_code_and_has_no_logout_command()
    {
        var host = new FakeLoginHost { LoginLines = ["To authenticate, visit https://github.com/login/device and enter code 92EC-55BB"] };
        host.Env["COPILOT_HOME"] = Path.Combine(Path.GetTempPath(), "d3sk-no-such-copilot-" + Guid.NewGuid().ToString("N"));
        host.Env["PATH"] = "";
        var logins = new CliLogins(host, timings: Quick, home: Path.GetTempPath());
        var started = await logins.StartAsync("copilot", "/bin/copilot", Ct);
        Assert.Equal("https://github.com/login/device", started.Url);
        Assert.Equal("92EC-55BB", started.UserCode);
        Assert.False(started.NeedsCode);
        Assert.False((await logins.StatusAsync("copilot", "/bin/copilot", Ct)).SignedIn);
        host.Started[0].Exit(0); // the login ended cleanly: trusted over a config not read back yet
        Assert.True((await logins.StatusAsync("copilot", "/bin/copilot", Ct)).SignedIn);
        var e = await Assert.ThrowsAsync<LoginException>(() => logins.LogoutAsync("copilot", "/bin/copilot", Ct));
        Assert.Contains("/logout", e.Message);
    }

    private sealed class ManualTime : TimeProvider
    {
        private long _now;

        public override long TimestampFrequency => TimeSpan.TicksPerSecond;

        public override long GetTimestamp() => _now;

        public void Advance(TimeSpan by) => _now += by.Ticks;
    }
}
