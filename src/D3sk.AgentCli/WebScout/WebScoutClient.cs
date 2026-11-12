using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace D3sk.AgentCli.WebScout;

/// <summary>
/// Calls the scout's API (<c>/status</c>, <c>/search</c>, <c>/fetch</c>) with the key from the
/// keychain, only over a user-only socket, a user-only pipe or https. A scout that offers neither
/// (plain http only, or no key check: a request without the key is answered) gives
/// <see cref="ScoutNeedsUpdate"/>; the client never retries over plain http and never sends the key
/// to a server it has not seen refuse a request without one. Redirects are not followed.
/// </summary>
public sealed class WebScoutClient : IDisposable
{
    private const string Host = "d3skwebscout.local";
    private readonly ScoutEndpoint _endpoint;
    private readonly IScoutKeySource _keys;
    private readonly string _caller;
    private readonly HttpClient? _http;
    private volatile bool _verified;

    /// <summary>Builds a client; <paramref name="handler"/> replaces the transport (tests, a custom TLS setup).</summary>
    public WebScoutClient(ScoutEndpoint endpoint, IScoutKeySource keys, string caller = "agent-cli-bridge", HttpMessageHandler? handler = null)
    {
        _endpoint = endpoint;
        _keys = keys;
        _caller = caller;
        if (endpoint.Transport == ScoutTransport.PlainHttp)
        {
            return; // never connected
        }
        _http = new HttpClient(handler ?? NewHandler(endpoint), disposeHandler: true)
        {
            BaseAddress = new Uri(endpoint.Transport == ScoutTransport.Https ? endpoint.Address : $"http://{Host}"),
            Timeout = Timeout.InfiniteTimeSpan, // a fetch may wait for the owner at a CAPTCHA; the token bounds it
        };
    }

    /// <summary>The scout's <c>/status</c>.</summary>
    public Task<ScoutResult> StatusAsync(CancellationToken ct) => SendAsync(HttpMethod.Get, "/status", null, ct);

    /// <summary>A web search; <paramref name="engine"/> is auto, google, duckduckgo, bing, brave or both.</summary>
    public Task<ScoutResult> SearchAsync(string query, string engine, int count, CancellationToken ct) =>
        SendAsync(HttpMethod.Post, "/search", Body(w =>
        {
            w.WriteString("query", query);
            w.WriteString("engine", engine);
            w.WriteNumber("n", count);
        }), ct);

    /// <summary>Reads a page; a page rated high is withheld unless <paramref name="allowRisky"/>.</summary>
    public Task<ScoutResult> FetchAsync(string url, int offset, bool allowRisky, CancellationToken ct) =>
        SendAsync(HttpMethod.Post, "/fetch", Body(w =>
        {
            w.WriteString("url", url);
            w.WriteNumber("offset", offset);
            w.WriteBoolean("allow_risky", allowRisky);
        }), ct);

    /// <inheritdoc />
    public void Dispose() => _http?.Dispose();

    private static HttpMessageHandler NewHandler(ScoutEndpoint endpoint)
    {
        var handler = new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false };
        if (endpoint.Transport == ScoutTransport.UserSocket)
        {
            handler.ConnectCallback = (_, ct) => ScoutTransports.ConnectSocketAsync(endpoint.Address, ct);
        }
        else if (endpoint.Transport == ScoutTransport.UserPipe)
        {
            handler.ConnectCallback = (_, ct) => ScoutTransports.ConnectPipeAsync(endpoint.Address, ct);
        }
        return handler;
    }

    private static string Body(Action<Utf8JsonWriter> fill)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
        {
            writer.WriteStartObject();
            fill(writer);
            writer.WriteEndObject();
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }

    private async Task<ScoutResult> SendAsync(HttpMethod method, string path, string? body, CancellationToken ct)
    {
        if (_http is null)
        {
            return new ScoutNeedsUpdate(ScoutNeedsUpdate.ServiceName, "the scout only offers plain http; it needs the update that adds a key-checked endpoint");
        }
        try
        {
            if (!_verified)
            {
                var probe = await ProbeAsync(ct).ConfigureAwait(false);
                if (probe is not null)
                {
                    return probe;
                }
            }
            var key = _keys.ReadKey();
            if (string.IsNullOrEmpty(key))
            {
                return new ScoutKeyMissing();
            }
            using var response = await CallAsync(method, path, body, key, ct).ConfigureAwait(false);
            return await ReadAsync(response, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            return Classify(ex);
        }
    }

    // A request without the key must be refused. Only then may the key travel to this server.
    private async Task<ScoutResult?> ProbeAsync(CancellationToken ct)
    {
        using var response = await CallAsync(HttpMethod.Get, "/status", null, null, ct).ConfigureAwait(false);
        if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
        {
            _verified = true;
            return null;
        }
        return new ScoutNeedsUpdate(
            ScoutNeedsUpdate.ServiceName,
            $"the scout answered a request without a key (status {(int)response.StatusCode}); it does not check the key and needs the update");
    }

    private async Task<HttpResponseMessage> CallAsync(HttpMethod method, string path, string? body, string? key, CancellationToken ct)
    {
        using var request = new HttpRequestMessage(method, path);
        request.Headers.TryAddWithoutValidation("X-Caller", _caller);
        if (key is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
        }
        if (body is not null)
        {
            request.Content = new StringContent(body, Encoding.UTF8, "application/json");
        }
        return await _http!.SendAsync(request, HttpCompletionOption.ResponseContentRead, ct).ConfigureAwait(false);
    }

    private static async Task<ScoutResult> ReadAsync(HttpResponseMessage response, CancellationToken ct)
    {
        if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
        {
            return new ScoutKeyRejected();
        }
        var json = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        return response.IsSuccessStatusCode ? new ScoutOk(json) : new ScoutFailed((int)response.StatusCode, json);
    }

    private static ScoutResult Classify(HttpRequestException ex)
    {
        for (Exception? inner = ex; inner is not null; inner = inner.InnerException)
        {
            if (inner is ScoutRefusedException refused)
            {
                return new ScoutRefused(refused.Message);
            }
        }
        return new ScoutDown("the scout does not answer: is it running?");
    }
}
