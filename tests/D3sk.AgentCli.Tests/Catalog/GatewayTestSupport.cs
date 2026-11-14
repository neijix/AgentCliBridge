using System.Net;
using System.Net.Sockets;
using System.Text;

namespace D3sk.AgentCli.Tests.Catalog;

/// <summary>What a <see cref="LoopbackGateway"/> saw of one request.</summary>
/// <param name="Path">Path and query.</param>
/// <param name="Headers">Every request header, name to value.</param>
public sealed record SeenRequest(string Path, IReadOnlyDictionary<string, string> Headers)
{
    /// <summary>Whether a header of that name (any case) was sent.</summary>
    public bool Has(string name) => Headers.Keys.Any(k => string.Equals(k, name, StringComparison.OrdinalIgnoreCase));
}

/// <summary>A loopback http server recording each request and answering a given status and body.</summary>
public sealed class LoopbackGateway : IDisposable
{
    /// <summary>A minimal neutral <c>/v1/models</c> answer.</summary>
    public const string ModelsAnswer = """{"data": [{"id": "claude-opus-5-5", "display_name": "Opus"}]}""";

    private readonly HttpListener _listener = new();
    private readonly List<SeenRequest> _seen = [];
    private readonly Task _loop;

    /// <summary>Starts on a free loopback port.</summary>
    public LoopbackGateway()
    {
        var probe = TcpListener.Create(0);
        probe.Start();
        var port = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        BaseUrl = $"http://127.0.0.1:{port}";
        _listener.Prefixes.Add($"{BaseUrl}/");
        _listener.Start();
        _loop = Task.Run(Serve);
    }

    /// <summary>The server's origin, without a trailing slash.</summary>
    public string BaseUrl { get; }

    /// <summary>The status to answer; a 3xx also sets <see cref="RedirectTo"/>.</summary>
    public int Status { get; set; } = 200;

    /// <summary>The body to answer.</summary>
    public byte[] Body { get; set; } = Encoding.UTF8.GetBytes(ModelsAnswer);

    /// <summary>Where a 3xx points.</summary>
    public string? RedirectTo { get; set; }

    /// <summary>The requests so far, in order.</summary>
    public IReadOnlyList<SeenRequest> Seen
    {
        get
        {
            lock (_seen)
            {
                return [.. _seen];
            }
        }
    }

    private void Serve()
    {
        while (_listener.IsListening)
        {
            HttpListenerContext ctx;
            try
            {
                ctx = _listener.GetContext();
            }
            catch (Exception)
            {
                return;
            }
            var headers = ctx.Request.Headers.AllKeys.Where(k => k is not null)
                .ToDictionary(k => k!, k => ctx.Request.Headers[k] ?? "", StringComparer.OrdinalIgnoreCase);
            lock (_seen)
            {
                _seen.Add(new SeenRequest(ctx.Request.Url!.PathAndQuery, headers));
            }
            try
            {
                ctx.Response.StatusCode = Status;
                if (Status is >= 300 and < 400 && RedirectTo is not null)
                {
                    ctx.Response.RedirectLocation = RedirectTo;
                }
                ctx.Response.ContentType = "application/json";
                ctx.Response.OutputStream.Write(Body);
                ctx.Response.Close();
            }
            catch (Exception ex) when (ex is HttpListenerException or IOException or ObjectDisposedException or InvalidOperationException)
            {
                // The client gave up mid-answer (the size-limit case): expected.
                ctx.Response.Abort();
            }
        }
    }

    /// <inheritdoc />
    public void Dispose()
    {
        try
        {
            _listener.Stop();
        }
        catch (ObjectDisposedException)
        {
            // already stopped
        }
        try
        {
            _loop.Wait(TimeSpan.FromSeconds(5));
        }
        catch (AggregateException)
        {
            // the loop ends by its listener stopping; nothing else to observe
        }
        _listener.Close();
    }
}
