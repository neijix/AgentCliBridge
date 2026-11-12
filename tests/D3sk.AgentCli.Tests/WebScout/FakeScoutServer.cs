using System.Net;
using System.Net.Sockets;
using System.Text;

namespace D3sk.AgentCli.Tests.WebScout;

/// <summary>One request a fake scout saw.</summary>
public sealed record SeenRequest(string Method, string Path, string? Authorization, string Body);

/// <summary>A tiny HTTP/1.1 server on a TCP port or a Unix socket; it records every request it gets.</summary>
public sealed class FakeScoutServer : IDisposable
{
    private readonly Socket _listener;
    private readonly Func<SeenRequest, (int Status, string Body)> _respond;
    private readonly CancellationTokenSource _stop = new();
    private readonly List<SeenRequest> _seen = [];
    private readonly Task _loop;

    private FakeScoutServer(Socket listener, Func<SeenRequest, (int, string)> respond)
    {
        _listener = listener;
        _respond = respond;
        _loop = Task.Run(AcceptLoopAsync);
    }

    /// <summary>Every request so far.</summary>
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

    /// <summary>The TCP port, when started with <see cref="Tcp"/>.</summary>
    public int Port => ((IPEndPoint)_listener.LocalEndPoint!).Port;

    public static FakeScoutServer Tcp(Func<SeenRequest, (int, string)> respond)
    {
        var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        socket.Bind(new IPEndPoint(IPAddress.Loopback, 0));
        socket.Listen(8);
        return new FakeScoutServer(socket, respond);
    }

    public static FakeScoutServer Unix(string path, Func<SeenRequest, (int, string)> respond)
    {
        var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        socket.Bind(new UnixDomainSocketEndPoint(path));
        socket.Listen(8);
        return new FakeScoutServer(socket, respond);
    }

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Dispose();
        try
        {
            _loop.Wait(TimeSpan.FromSeconds(2));
        }
        catch (AggregateException)
        {
        }
    }

    private async Task AcceptLoopAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            Socket client;
            try
            {
                client = await _listener.AcceptAsync(_stop.Token);
            }
            catch (Exception ex) when (ex is OperationCanceledException or ObjectDisposedException or SocketException)
            {
                return;
            }
            _ = Task.Run(() => ServeAsync(client));
        }
    }

    private async Task ServeAsync(Socket client)
    {
        using var stream = new NetworkStream(client, ownsSocket: true);
        try
        {
            while (await ReadRequestAsync(stream) is { } request)
            {
                lock (_seen)
                {
                    _seen.Add(request);
                }
                var (status, body) = _respond(request);
                var bytes = Encoding.UTF8.GetBytes(body);
                var head = $"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {bytes.Length}\r\n\r\n";
                await stream.WriteAsync(Encoding.ASCII.GetBytes(head));
                await stream.WriteAsync(bytes);
            }
        }
        catch (Exception ex) when (ex is IOException or OperationCanceledException or ObjectDisposedException)
        {
        }
    }

    private static async Task<SeenRequest?> ReadRequestAsync(Stream stream)
    {
        var head = new StringBuilder();
        var one = new byte[1];
        while (!head.ToString().EndsWith("\r\n\r\n", StringComparison.Ordinal))
        {
            if (await stream.ReadAsync(one) == 0)
            {
                return null;
            }
            head.Append((char)one[0]);
        }
        var lines = head.ToString().Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        var first = lines[0].Split(' ');
        string? auth = null;
        var length = 0;
        foreach (var line in lines.Skip(1))
        {
            var colon = line.IndexOf(':');
            var name = line[..colon];
            var value = line[(colon + 1)..].Trim();
            if (name.Equals("Authorization", StringComparison.OrdinalIgnoreCase))
            {
                auth = value;
            }
            else if (name.Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
            {
                length = int.Parse(value);
            }
        }
        var body = new byte[length];
        var read = 0;
        while (read < length)
        {
            var n = await stream.ReadAsync(body.AsMemory(read));
            if (n == 0)
            {
                return null;
            }
            read += n;
        }
        return new SeenRequest(first[0], first[1], auth, Encoding.UTF8.GetString(body));
    }
}
