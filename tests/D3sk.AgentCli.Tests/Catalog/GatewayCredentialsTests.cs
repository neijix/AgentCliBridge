using System.Net;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Tests.Catalog;

public sealed class GatewayCredentialsTests : IDisposable
{
    private static readonly Dictionary<string, string> Credentials = new(StringComparer.OrdinalIgnoreCase)
    {
        ["X-Team"] = "blue",
        ["x-api-key"] = "key-1",
        ["Authorization"] = "Bearer token-1",
    };

    private readonly string _dir = Directory.CreateTempSubdirectory("gwcred").FullName;
    private readonly LoopbackGateway _server = new();

    public void Dispose()
    {
        _server.Dispose();
        Directory.Delete(_dir, recursive: true);
    }

    private static CatalogAgent Claude() => new("claude", "claude", ["claude-opus-5-5"], true, "/bin/claude");

    [Fact]
    public void The_real_fetch_sends_no_credential_to_plain_http_loopback_included()
    {
        var node = CatalogIo.FetchJson($"{_server.BaseUrl}/v1/models?limit=1000", Credentials);
        Assert.Equal("claude-opus-5-5", node!["data"]![0]!["id"]!.ToString());
        var seen = Assert.Single(_server.Seen);
        Assert.False(seen.Has("Authorization"));
        Assert.False(seen.Has("x-api-key"));
        Assert.False(seen.Has("X-Team"));
        Assert.True(seen.Has("Accept"));
        Assert.True(seen.Has("User-Agent"));
    }

    [Fact]
    public void A_redirect_is_not_followed_with_or_without_headers()
    {
        _server.Status = 302;
        _server.RedirectTo = "/elsewhere";
        foreach (var headers in new IReadOnlyDictionary<string, string>?[] { null, Credentials })
        {
            var ex = Assert.Throws<HttpRequestException>(() => CatalogIo.FetchJson($"{_server.BaseUrl}/moved", headers));
            Assert.Equal(HttpStatusCode.Found, ex.StatusCode);
        }
        Assert.All(_server.Seen, s => Assert.Equal("/moved", s.Path));
    }

    [Fact]
    public void The_size_limit_still_holds_with_headers()
    {
        _server.Body = new byte[CatalogIo.GatewayMaxBytes + 1];
        Assert.Contains("over", Assert.Throws<ArgumentException>(() => CatalogIo.FetchJson($"{_server.BaseUrl}/v1/models", Credentials)).Message);
    }

    [Fact]
    public void A_gateway_that_never_answers_is_given_up_on_at_the_gateway_timeout()
    {
        _server.NoAnswer = true;
        Assert.True(CatalogIo.GatewayTimeout <= TimeSpan.FromSeconds(10), "a gateway read must stay short");
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var ex = Record.Exception(() => CatalogIo.FetchJson($"{_server.BaseUrl}/v1/models", Credentials));
        watch.Stop();
        // HttpClient.Timeout surfaces as a TaskCanceledException (an OperationCanceledException).
        Assert.IsAssignableFrom<OperationCanceledException>(ex);
        Assert.True(watch.Elapsed >= CatalogIo.GatewayTimeout * 0.8, $"gave up too early: {watch.Elapsed}");
        Assert.True(watch.Elapsed < CatalogIo.GatewayTimeout + TimeSpan.FromSeconds(3), $"gave up too late: {watch.Elapsed}");
        Assert.Single(_server.Seen);
    }

    [Fact]
    public void An_https_request_carries_the_headers_and_its_own_accept_and_user_agent_win()
    {
        var given = new Dictionary<string, string>(Credentials) { ["accept"] = "text/html", ["User-Agent"] = "spoof" };
        using var request = CatalogIo.BuildGatewayRequest(new Uri("https://ai.example.com/v1/models"), given);
        Assert.Equal("blue", Assert.Single(request.Headers.GetValues("X-Team")));
        Assert.Equal("key-1", Assert.Single(request.Headers.GetValues("x-api-key")));
        Assert.Equal("Bearer token-1", Assert.Single(request.Headers.GetValues("Authorization")));
        Assert.Equal("application/json", Assert.Single(request.Headers.Accept).ToString());
        Assert.Equal("D3sk.AgentCli", request.Headers.UserAgent.ToString());
    }

    [Fact]
    public void A_plain_http_request_carries_none_of_them()
    {
        using var request = CatalogIo.BuildGatewayRequest(new Uri("http://localhost:4000/v1/models"), Credentials);
        Assert.False(request.Headers.Contains("Authorization"));
        Assert.False(request.Headers.Contains("x-api-key"));
        Assert.False(request.Headers.Contains("X-Team"));
    }

    [Fact]
    public void A_header_the_stack_refuses_is_a_catalog_failure_not_an_exception_out_of_refresh()
    {
        var bad = new Dictionary<string, string> { ["Content-Type"] = "text/plain" };
        Assert.Throws<ArgumentException>(() => CatalogIo.BuildGatewayRequest(new Uri("https://ai.example.com"), bad).Dispose());
        var catalog = new ModelCatalog(Path.Combine(_dir, "known.json"), (url, h) => CatalogIo.FetchJson(url, h), clock: () => 1000);
        catalog.Refresh([Claude()], claudeGateway: "https://127.0.0.1:1", claudeGatewayHeaders: bad);
        Assert.Equal(["claude-opus-5-5"], catalog.Merge(Claude()).Models);
    }

    [Fact]
    public void A_value_that_is_not_ascii_is_refused_before_sending_not_blamed_on_the_network()
    {
        var accented = new Dictionary<string, string> { ["X-Team"] = "caf" + (char)0xE9 };
        Assert.Throws<ArgumentException>(() => CatalogIo.BuildGatewayRequest(new Uri("https://ai.example.com"), accented).Dispose());
    }

    [Fact]
    public void A_gateway_that_never_answers_is_asked_again_a_minute_later_and_refresh_returns()
    {
        var calls = 0;
        var now = 1000.0;
        var catalog = new ModelCatalog(Path.Combine(_dir, "known.json"), (url, h) =>
        {
            calls++;
            throw new TaskCanceledException("timed out");
        }, clock: () => now);
        catalog.Refresh([Claude()], claudeGateway: "https://ai.example.com", claudeGatewayHeaders: Credentials);
        Assert.Equal(["claude-opus-5-5"], catalog.Merge(Claude()).Models);
        now += ModelCatalog.GatewayRetry + 1;
        catalog.Refresh([Claude()], claudeGateway: "https://ai.example.com", claudeGatewayHeaders: Credentials);
        Assert.Equal(2, calls);
    }

    [Theory]
    [InlineData("https://ai.example.com", true)]
    [InlineData("http://127.0.0.1:4000", false)]
    [InlineData("http://[::1]:4000", false)]
    [InlineData("http://localhost:4000", false)]
    [InlineData("http://ai.example.com", false)]
    [InlineData("http://10.0.0.5:8080", false)]
    public void The_catalog_hands_the_headers_to_the_fetch_only_for_an_https_gateway(string gateway, bool carries)
    {
        IReadOnlyDictionary<string, string>? got = null;
        var catalog = new ModelCatalog(Path.Combine(_dir, "known.json"), (url, h) =>
        {
            got = h;
            return JsonNode.Parse(LoopbackGateway.ModelsAnswer);
        }, clock: () => 1000);
        catalog.Refresh([Claude()], claudeGateway: gateway, claudeGatewayHeaders: Credentials);
        Assert.NotNull(got);
        Assert.Equal(carries ? Credentials.Count : 0, got.Count);
    }

    [Fact]
    public void The_one_argument_constructor_fetches_a_gateway_without_headers()
    {
        var urls = new List<string>();
        var catalog = new ModelCatalog(Path.Combine(_dir, "known.json"), fetch: url =>
        {
            urls.Add(url);
            return JsonNode.Parse(LoopbackGateway.ModelsAnswer);
        }, clock: () => 1000);
        catalog.Refresh([Claude()], claudeGateway: "https://ai.example.com", claudeGatewayHeaders: Credentials);
        Assert.Equal(["https://ai.example.com/v1/models?limit=1000"], urls);
    }
}
