using System.IO.Pipes;
using System.Net.Sockets;

namespace D3sk.AgentCli.WebScout;

/// <summary>The client refused a transport; carried out of the connect callback, turned into <see cref="ScoutRefused"/>.</summary>
internal sealed class ScoutRefusedException(string reason) : Exception(reason);

/// <summary>Opens the user-only connections. The check runs at connect time, so a socket swapped in later is caught too.</summary>
internal static class ScoutTransports
{
    private const UnixFileMode OthersAny =
        UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute |
        UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute;

    /// <summary>Throws when anyone but the owner could reach the socket or replace it.</summary>
    internal static void CheckUserOnly(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            throw new ScoutRefusedException("a Unix socket has no owner check on Windows; use a named pipe");
        }
        if (!File.Exists(path))
        {
            throw new IOException("the scout's socket does not exist");
        }
        if ((File.GetUnixFileMode(path) & OthersAny) != 0)
        {
            throw new ScoutRefusedException("the scout's socket is reachable by other users (mode must leave group and others out)");
        }
        var folder = Path.GetDirectoryName(Path.GetFullPath(path)) ?? "/";
        if ((File.GetUnixFileMode(folder) & (UnixFileMode.GroupWrite | UnixFileMode.OtherWrite)) != 0)
        {
            throw new ScoutRefusedException("the scout's socket folder is writable by other users");
        }
    }

    internal static async ValueTask<Stream> ConnectSocketAsync(string path, CancellationToken ct)
    {
        CheckUserOnly(path);
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
    }

    internal static async ValueTask<Stream> ConnectPipeAsync(string name, CancellationToken ct)
    {
        var pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        try
        {
            await pipe.ConnectAsync(ct).ConfigureAwait(false);
            return pipe;
        }
        catch
        {
            await pipe.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }
}
