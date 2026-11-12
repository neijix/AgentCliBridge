using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Runtime.Versioning;

namespace D3sk.AgentCli.Local;

/// <summary>
/// A checked way to call D3SKMODEL: a keyed endpoint over a user-only socket or TLS. It is built only
/// after the key exists and an unkeyed probe was refused (401), so the key never goes to a server that
/// does not check one, and nothing is ever sent over plain HTTP to a TCP port.
/// </summary>
public sealed class MlxLink : IDisposable
{
    private static readonly Uri SocketBase = new("http://mlx.local/");

    private readonly string? _key;

    private MlxLink(LocalServiceState state, HttpClient? client, string? key)
    {
        State = state;
        Client = client;
        _key = key;
    }

    /// <summary>What was found; <see cref="LocalServiceState.IsReady"/> when the link may be used.</summary>
    public LocalServiceState State { get; }

    internal HttpClient? Client { get; }

    /// <summary>Finds out whether MLX can be called, and builds the link when it can.</summary>
    public static async Task<MlxLink> ConnectAsync(MlxOptions options, CancellationToken cancellationToken = default)
    {
        var key = options.KeySource();
        if (string.IsNullOrWhiteSpace(key))
        {
            return Blocked(LocalServiceState.NoKey(MlxOptions.Name, $"No key for {MlxOptions.Name} in the keychain ({MlxOptions.KeychainEntry}). Run `d3skmodel setup`."));
        }

        var client = BuildClient(options, out var refused);
        if (client is null)
        {
            return Blocked(refused ?? await MissingSocketAsync(options, cancellationToken).ConfigureAwait(false));
        }

        var state = await ProbeAsync(client, options, cancellationToken).ConfigureAwait(false);
        if (!state.IsReady)
        {
            client.Dispose();
            return Blocked(state);
        }

        return new MlxLink(state, client, key.Trim());
    }

    /// <summary>Sends one request with the bearer key. Only on a ready link.</summary>
    internal Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (Client is null || _key is null)
        {
            throw new InvalidOperationException("The link is not ready.");
        }

        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _key);
        return Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
    }

    /// <inheritdoc />
    public void Dispose() => Client?.Dispose();

    /// <summary>The request URI for a path under the endpoint (<c>/v1/...</c>).</summary>
    internal Uri Url(string path) => new(Client!.BaseAddress!, path);

    private static MlxLink Blocked(LocalServiceState state) => new(state, null, null);

    private static HttpClient? BuildClient(MlxOptions options, out LocalServiceState? refused)
    {
        refused = null;
        if (options.HttpsBase is { } https)
        {
            if (https.Scheme != Uri.UriSchemeHttps)
            {
                refused = LocalServiceState.NeedsUpdate(MlxOptions.Name, "plain HTTP is refused; it must offer TLS or a user-only socket.");
                return null;
            }

            return new HttpClient(new SocketsHttpHandler { UseProxy = false }) { BaseAddress = https, Timeout = Timeout.InfiniteTimeSpan };
        }

        if (OperatingSystem.IsWindows())
        {
            refused = LocalServiceState.NeedsUpdate(MlxOptions.Name, "its Windows endpoint (a named pipe) is not available yet.");
            return null;
        }

        if (!File.Exists(options.SocketPath))
        {
            return null;
        }

        if (UnsafeSocket(options.SocketPath) is { } why)
        {
            refused = LocalServiceState.NeedsUpdate(MlxOptions.Name, why);
            return null;
        }

        var path = options.SocketPath;
        var handler = new SocketsHttpHandler
        {
            UseProxy = false,
            ConnectCallback = async (_, ct) =>
            {
                var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
                try
                {
                    await socket.ConnectAsync(new UnixDomainSocketEndPoint(path), ct).ConfigureAwait(false);
                    return new NetworkStream(socket, ownsSocket: true);
                }
                catch
                {
                    socket.Dispose();
                    throw;
                }
            },
        };
        return new HttpClient(handler) { BaseAddress = SocketBase, Timeout = Timeout.InfiniteTimeSpan };
    }

    /// <summary>Why the socket is not user-only, or null. A folder only its owner can enter keeps every other user from the socket, whatever the socket's own mode.</summary>
    [UnsupportedOSPlatform("windows")]
    private static string? UnsafeSocket(string socketPath)
    {
        const UnixFileMode Others = UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute
            | UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute;
        try
        {
            var folder = Path.GetDirectoryName(Path.GetFullPath(socketPath)) ?? "/";
            if ((File.GetUnixFileMode(folder) & Others) != 0)
            {
                return "its socket folder is open to other users (it must be 0700).";
            }

            return null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return "its socket could not be checked.";
        }
    }

    /// <summary>No socket: an old server still listens on the plain port (TCP connect only, nothing sent), or nothing runs.</summary>
    private static async Task<LocalServiceState> MissingSocketAsync(MlxOptions options, CancellationToken cancellationToken)
    {
        using var tcp = new TcpClient();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(options.ProbeTimeout);
        try
        {
            await tcp.ConnectAsync(IPAddress.Loopback, options.LegacyPortToProbe, timeout.Token).ConfigureAwait(false);
            return LocalServiceState.NeedsUpdate(MlxOptions.Name, "it only offers its old plain endpoint, which is never used.");
        }
        catch (Exception e) when (e is SocketException or OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            return LocalServiceState.NotRunning(MlxOptions.Name, $"{MlxOptions.Name} is not running on this computer. Start D3SKMODEL and try again.");
        }
    }

    /// <summary>An unkeyed request must be refused with 401; any other answer means the server checks no key.</summary>
    private static async Task<LocalServiceState> ProbeAsync(HttpClient client, MlxOptions options, CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(options.ProbeTimeout);
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(client.BaseAddress!, "/v1/models"));
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
            return response.StatusCode == HttpStatusCode.Unauthorized
                ? LocalServiceState.Ready(MlxOptions.Name)
                : LocalServiceState.NeedsUpdate(MlxOptions.Name, "it answers without checking a key.");
        }
        catch (Exception e) when (e is HttpRequestException or OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            return LocalServiceState.NotRunning(MlxOptions.Name, $"Could not reach {MlxOptions.Name} on this computer.");
        }
    }
}
