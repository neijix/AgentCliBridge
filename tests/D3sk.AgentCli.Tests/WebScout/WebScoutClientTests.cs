using System.Net;
using System.Runtime.Versioning;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Tests.WebScout;

[UnsupportedOSPlatform("windows")]
public sealed class WebScoutClientTests : IDisposable
{
    // Not a real credential: a made-up word the fake server compares.
    private const string TestKey = "fixture-scout-key";
    private readonly string _dir = Directory.CreateTempSubdirectory("scout").FullName;

    public WebScoutClientTests()
    {
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(_dir, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
    }

    public void Dispose()
    {
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(_dir, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        Directory.Delete(_dir, recursive: true);
    }

    private sealed class Key(string? value) : IScoutKeySource
    {
        public int Reads { get; private set; }

        public string? ReadKey()
        {
            Reads++;
            return value;
        }
    }

    private static (int, string) Keyed(SeenRequest r) =>
        r.Authorization == $"Bearer {TestKey}" ? (200, "{\"ok\":true}") : (401, "{\"detail\":\"missing or bad bearer token\"}");

    private string UserSocketPath() => Path.Combine(_dir, "webscout.sock");

    // A bound socket gets the umask's mode: make it user-only, as the scout's own setup does.
    private FakeScoutServer Serve(Func<SeenRequest, (int, string)> respond)
    {
        var server = FakeScoutServer.Unix(UserSocketPath(), respond);
        File.SetUnixFileMode(UserSocketPath(), UnixFileMode.UserRead | UnixFileMode.UserWrite);
        return server;
    }

    private static void SkipOnWindows() => Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket test");

    [Trait("Category", "Security")]
    [Fact]
    public async Task A_plain_http_scout_gives_needs_update_and_gets_no_request()
    {
        using var server = FakeScoutServer.Tcp(_ => (200, "{\"ok\":true}"));
        var key = new Key(TestKey);
        using var client = new WebScoutClient(ScoutEndpoint.FromUri(new Uri($"http://127.0.0.1:{server.Port}")), key);

        var ct = TestContext.Current.CancellationToken;
        foreach (var result in new[] { await client.StatusAsync(ct), await client.SearchAsync("q", "auto", 5, ct), await client.FetchAsync("https://a.b/", 0, false, ct) })
        {
            var update = Assert.IsType<ScoutNeedsUpdate>(result);
            Assert.Equal("web scout", update.Service);
        }
        Assert.Empty(server.Seen);
        Assert.Equal(0, key.Reads);
    }

    [Trait("Category", "Security")]
    [Fact]
    public async Task A_server_that_answers_without_the_key_gets_needs_update_and_never_sees_the_key()
    {
        SkipOnWindows();
        using var server = Serve(_ => (200, "{\"ok\":true}"));
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key(TestKey));

        var result = await client.StatusAsync(TestContext.Current.CancellationToken);

        Assert.IsType<ScoutNeedsUpdate>(result);
        Assert.All(server.Seen, r => Assert.Null(r.Authorization));
        Assert.Single(server.Seen);
    }

    [Fact]
    public async Task Over_a_user_only_socket_the_key_is_sent_after_the_refusal_probe()
    {
        SkipOnWindows();
        using var server = Serve(Keyed);
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key(TestKey), caller: "d3skhand");
        var ct = TestContext.Current.CancellationToken;

        var status = await client.StatusAsync(ct);
        var search = await client.SearchAsync("quebec \"maple\"", "brave", 3, ct);
        var fetch = await client.FetchAsync("https://example.org/a", 4000, true, ct);

        Assert.Equal(new ScoutOk("{\"ok\":true}"), status);
        Assert.IsType<ScoutOk>(search);
        Assert.IsType<ScoutOk>(fetch);
        Assert.Null(server.Seen[0].Authorization); // the one probe, once
        Assert.All(server.Seen.Skip(1), r => Assert.Equal($"Bearer {TestKey}", r.Authorization));
        Assert.Equal(4, server.Seen.Count);
        Assert.Equal("{\"query\":\"quebec \\u0022maple\\u0022\",\"engine\":\"brave\",\"n\":3}", server.Seen[2].Body);
        Assert.Equal("{\"url\":\"https://example.org/a\",\"offset\":4000,\"allow_risky\":true}", server.Seen[3].Body);
        Assert.Equal(["GET", "GET", "POST", "POST"], server.Seen.Select(r => r.Method));
    }

    [Fact]
    public async Task A_missing_key_sends_no_key_and_is_typed()
    {
        SkipOnWindows();
        using var server = Serve(Keyed);
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key(null));

        Assert.IsType<ScoutKeyMissing>(await client.StatusAsync(TestContext.Current.CancellationToken));
        Assert.All(server.Seen, r => Assert.Null(r.Authorization));
    }

    [Fact]
    public async Task A_wrong_key_is_rejected_and_an_error_status_keeps_its_body()
    {
        SkipOnWindows();
        using var server = Serve(r =>
            r.Authorization is null ? (401, "{}") : r.Path == "/fetch" ? (503, "{\"kind\":\"captcha\"}") : (403, "{}"));
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key("another-word"));
        var ct = TestContext.Current.CancellationToken;

        Assert.IsType<ScoutKeyRejected>(await client.StatusAsync(ct));
        Assert.Equal(new ScoutFailed(503, "{\"kind\":\"captcha\"}"), await client.FetchAsync("https://a.b/", 0, false, ct));
    }

    [Fact]
    public async Task No_listener_is_down()
    {
        SkipOnWindows();
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key(TestKey));

        Assert.IsType<ScoutDown>(await client.StatusAsync(TestContext.Current.CancellationToken));
    }

    [Trait("Category", "Security")]
    [Theory]
    [InlineData(UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.GroupRead | UnixFileMode.GroupWrite)]
    [InlineData(UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.OtherWrite)]
    public async Task A_socket_others_can_reach_is_refused_and_the_key_is_not_sent(UnixFileMode mode)
    {
        SkipOnWindows();
        using var server = Serve(Keyed);
        File.SetUnixFileMode(UserSocketPath(), mode);
        var key = new Key(TestKey);
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), key);

        Assert.IsType<ScoutRefused>(await client.StatusAsync(TestContext.Current.CancellationToken));
        Assert.Empty(server.Seen);
        Assert.Equal(0, key.Reads);
    }

    [Trait("Category", "Security")]
    [Fact]
    public async Task A_socket_in_a_folder_others_can_write_is_refused()
    {
        SkipOnWindows();
        using var server = Serve(Keyed);
        File.SetUnixFileMode(UserSocketPath(), UnixFileMode.UserRead | UnixFileMode.UserWrite);
        File.SetUnixFileMode(_dir, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute | UnixFileMode.OtherWrite);
        using var client = new WebScoutClient(ScoutEndpoint.UserSocket(UserSocketPath()), new Key(TestKey));

        Assert.IsType<ScoutRefused>(await client.StatusAsync(TestContext.Current.CancellationToken));
        Assert.Empty(server.Seen);
    }

    [Trait("Category", "Security")]
    [Fact]
    public async Task Https_sends_the_key_only_after_the_refusal_probe_and_never_follows_a_redirect()
    {
        var handler = new Scripted(r =>
        {
            if (r.RequestUri!.AbsolutePath == "/fetch")
            {
                var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
                redirect.Headers.Location = new Uri("http://127.0.0.1:1/steal");
                return redirect;
            }
            return new HttpResponseMessage(r.Headers.Authorization is null ? HttpStatusCode.Unauthorized : HttpStatusCode.OK) { Content = new StringContent("{}") };
        });
        using var client = new WebScoutClient(ScoutEndpoint.FromUri(new Uri("https://scout.example:4821/")), new Key(TestKey), handler: handler);
        var ct = TestContext.Current.CancellationToken;

        Assert.IsType<ScoutOk>(await client.StatusAsync(ct));
        Assert.IsType<ScoutFailed>(await client.FetchAsync("https://a.b/", 0, false, ct));

        Assert.All(handler.Requests, r => Assert.Equal("https", r.RequestUri!.Scheme));
        Assert.Null(handler.Requests[0].Headers.Authorization);
        Assert.All(handler.Requests.Skip(1), r => Assert.Equal("Bearer", r.Headers.Authorization!.Scheme));
    }

    [Fact]
    public void An_http_address_is_plain_and_an_https_one_is_not()
    {
        Assert.Equal(ScoutTransport.PlainHttp, ScoutEndpoint.FromUri(new Uri("http://127.0.0.1:4820/x")).Transport);
        Assert.Equal(ScoutTransport.Https, ScoutEndpoint.FromUri(new Uri("https://h:1/x")).Transport);
    }

    private sealed class Scripted(Func<HttpRequestMessage, HttpResponseMessage> answer) : HttpMessageHandler
    {
        public List<HttpRequestMessage> Requests { get; } = [];

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            return Task.FromResult(answer(request));
        }
    }
}
