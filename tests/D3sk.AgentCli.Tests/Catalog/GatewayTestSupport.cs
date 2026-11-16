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

    private readonly HttpListener _listener;
    private readonly List<SeenRequest> _seen = [];
    private readonly List<HttpListenerContext> _held = [];
    private readonly Task _loop;

    /// <summary>Starts on a free loopback port.</summary>
    public LoopbackGateway()
    {
        (_listener, var port) = StartOnFreePort();
        BaseUrl = $"http://127.0.0.1:{port}";
        _loop = Task.Run(Serve);
    }

    /// <summary>
    /// A started <see cref="HttpListener"/> on a free loopback port. The port is probed then bound, and
    /// a test running in parallel can take it in between ("Address already in use"): a failed start
    /// leaves the listener unusable, so each attempt is a new listener on a new port.
    /// </summary>
    public static (HttpListener Listener, int Port) StartOnFreePort()
    {
        for (var attempt = 1; ; attempt++)
        {
            var probe = TcpListener.Create(0);
            probe.Start();
            var port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            var listener = new HttpListener();
            listener.Prefixes.Add($"http://127.0.0.1:{port}/");
            try
            {
                listener.Start();
                return (listener, port);
            }
            catch (HttpListenerException) when (attempt < 10)
            {
                listener.Close();
            }
        }
    }

    /// <summary>The server's origin, without a trailing slash.</summary>
    public string BaseUrl { get; }

    /// <summary>The status to answer; a 3xx also sets <see cref="RedirectTo"/>.</summary>
    public int Status { get; set; } = 200;

    /// <summary>The body to answer.</summary>
    public byte[] Body { get; set; } = Encoding.UTF8.GetBytes(ModelsAnswer);

    /// <summary>When set, a request is accepted and recorded but never answered (until the server stops).</summary>
    public bool NoAnswer { get; set; }

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
            if (NoAnswer)
            {
                // Held open with no response: Dispose aborts it once the listener stops.
                lock (_held)
                {
                    _held.Add(ctx);
                }
                continue;
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
                try
                {
                    ctx.Response.Abort();
                }
                catch (ObjectDisposedException)
                {
                    // the listener stopped under us
                }
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
        lock (_held)
        {
            foreach (var ctx in _held)
            {
                try
                {
                    ctx.Response.Abort();
                }
                catch (Exception ex) when (ex is ObjectDisposedException or HttpListenerException or InvalidOperationException)
                {
                    // already gone
                }
            }
        }
        try
        {
            _loop.Wait(TimeSpan.FromSeconds(5));
        }
        catch (AggregateException)
        {
            // the loop ends by its listener stopping; nothing else to observe
        }
        CloseStopped(_listener);
    }

    /// <summary>
    /// Closes a listener already stopped. On Linux the managed listener's Close removes the prefixes a
    /// second time, which binds the port again to look up its endpoint: when a parallel test has taken
    /// the freed port that bind throws "Address already in use". The port is released by then.
    /// </summary>
    public static void CloseStopped(HttpListener listener)
    {
        try
        {
            listener.Close();
        }
        catch (HttpListenerException)
        {
            // the port belongs to another test now; nothing of ours is left open
        }
    }
}
