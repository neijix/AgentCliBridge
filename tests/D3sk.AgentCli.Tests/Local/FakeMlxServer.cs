using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Runtime.Versioning;
using System.Text;

namespace D3sk.AgentCli.Tests.Local;

/// <summary>One request the fake server saw.</summary>
internal sealed record SeenRequest(string Method, string Path, string? Authorization, string Body);

/// <summary>What the fake server answers: a status and a body, optionally stalling after the body so a test can cancel.</summary>
internal sealed record FakeReply(int Status, string Body, string ContentType = "application/json", bool StallAfterBody = false, TimeSpan? HeadDelay = null);

/// <summary>A tiny HTTP/1.1 server on a Unix socket in a private (0700) folder, standing in for D3SKMODEL's keyed endpoint.</summary>
[UnsupportedOSPlatform("windows")]
internal sealed class FakeMlxServer : IDisposable
{
    private readonly Socket _listener = new(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
    private readonly CancellationTokenSource _stop = new();
    private readonly Func<SeenRequest, FakeReply> _handler;

    public FakeMlxServer(Func<SeenRequest, FakeReply> handler, UnixFileMode folderMode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute)
    {
        _handler = handler;
        Folder = Directory.CreateTempSubdirectory("mlx-fake-").FullName;
        File.SetUnixFileMode(Folder, folderMode);
        SocketPath = Path.Combine(Folder, "api.sock");
        _listener.Bind(new UnixDomainSocketEndPoint(SocketPath));
        _listener.Listen(8);
        _ = Task.Run(AcceptLoopAsync);
    }

    public string Folder { get; }

    public string SocketPath { get; }

    public ConcurrentQueue<SeenRequest> Requests { get; } = new();

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Dispose();
        try
        {
            File.SetUnixFileMode(Folder, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Directory.Delete(Folder, recursive: true);
        }
        catch (IOException)
        {
        }
    }

    private async Task AcceptLoopAsync()
    {
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var client = await _listener.AcceptAsync(_stop.Token);
                _ = Task.Run(() => ServeAsync(client));
            }
        }
        catch (Exception e) when (e is OperationCanceledException or ObjectDisposedException or SocketException)
        {
        }
    }

    private async Task ServeAsync(Socket client)
    {
        using var socket = client;
        await using var stream = new NetworkStream(socket);
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var request = await ReadRequestAsync(stream);
                if (request is null)
                {
                    return;
                }

                Requests.Enqueue(request);
                var reply = _handler(request);
                if (reply.HeadDelay is { } pause)
                {
                    await Task.Delay(pause, _stop.Token);
                }

                var body = Encoding.UTF8.GetBytes(reply.Body);
                var head = $"HTTP/1.1 {reply.Status} X\r\nContent-Type: {reply.ContentType}\r\nContent-Length: {(reply.StallAfterBody ? body.Length + 100 : body.Length)}\r\n\r\n";
                await stream.WriteAsync(Encoding.ASCII.GetBytes(head), _stop.Token);
                await stream.WriteAsync(body, _stop.Token);
                if (reply.StallAfterBody)
                {
                    await Task.Delay(Timeout.Infinite, _stop.Token);
                }
            }
        }
        catch (Exception e) when (e is OperationCanceledException or IOException or SocketException or ObjectDisposedException)
        {
        }
    }

    private static async Task<SeenRequest?> ReadRequestAsync(NetworkStream stream)
    {
        var buffer = new List<byte>();
        var one = new byte[1];
        while (!EndsWithBlankLine(buffer))
        {
            if (await stream.ReadAsync(one) == 0)
            {
                return null;
            }

            buffer.Add(one[0]);
        }

        var lines = Encoding.ASCII.GetString([.. buffer]).Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        var first = lines[0].Split(' ');
        string? auth = null;
        var length = 0;
        foreach (var line in lines.Skip(1))
        {
            var colon = line.IndexOf(':', StringComparison.Ordinal);
            var name = line[..colon];
            var value = line[(colon + 1)..].Trim();
            if (name.Equals("Authorization", StringComparison.OrdinalIgnoreCase))
            {
                auth = value;
            }
            else if (name.Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
            {
                length = int.Parse(value, System.Globalization.CultureInfo.InvariantCulture);
            }
        }

        var body = new byte[length];
        var read = 0;
        while (read < length)
        {
            var n = await stream.ReadAsync(body.AsMemory(read));
            if (n == 0)
            {
                break;
            }

            read += n;
        }

        return new SeenRequest(first[0], first[1], auth, Encoding.UTF8.GetString(body, 0, read));
    }

    private static bool EndsWithBlankLine(List<byte> b) =>
        b.Count >= 4 && b[^4] == '\r' && b[^3] == '\n' && b[^2] == '\r' && b[^1] == '\n';
}

/// <summary>A TCP listener standing in for a plain-HTTP server: it counts connections and the bytes sent to it, and never answers.</summary>
internal sealed class FakePlainServer : IDisposable
{
    private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource _stop = new();
    private int _connections;
    private int _bytes;

    public FakePlainServer()
    {
        _listener.Start();
        _ = Task.Run(AcceptLoopAsync);
    }

    public int Port => ((IPEndPoint)_listener.LocalEndpoint).Port;

    public int Connections => Volatile.Read(ref _connections);

    public int BytesReceived => Volatile.Read(ref _bytes);

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Stop();
    }

    private async Task AcceptLoopAsync()
    {
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var client = await _listener.AcceptTcpClientAsync(_stop.Token);
                Interlocked.Increment(ref _connections);
                _ = Task.Run(() => DrainAsync(client));
            }
        }
        catch (Exception e) when (e is OperationCanceledException or ObjectDisposedException or SocketException)
        {
        }
    }

    private async Task DrainAsync(TcpClient client)
    {
        using var tcp = client;
        var buffer = new byte[1024];
        try
        {
            int n;
            while ((n = await tcp.GetStream().ReadAsync(buffer, _stop.Token)) > 0)
            {
                Interlocked.Add(ref _bytes, n);
            }
        }
        catch (Exception e) when (e is OperationCanceledException or IOException or ObjectDisposedException)
        {
        }
    }
}
