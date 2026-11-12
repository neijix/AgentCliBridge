namespace D3sk.AgentCli.WebScout;

/// <summary>How the scout is reached.</summary>
public enum ScoutTransport
{
    /// <summary>A Unix domain socket only the current user can reach.</summary>
    UserSocket,
    /// <summary>A named pipe opened with the current-user-only option (Windows).</summary>
    UserPipe,
    /// <summary>An https address with a bearer key.</summary>
    Https,
    /// <summary>Plain http: never called; the client answers "service needs update".</summary>
    PlainHttp,
}

/// <summary>Where the scout listens. Only a user-only socket, a user-only pipe and https are ever called.</summary>
public sealed record ScoutEndpoint(ScoutTransport Transport, string Address)
{
    /// <summary>A Unix domain socket path.</summary>
    public static ScoutEndpoint UserSocket(string path) => new(ScoutTransport.UserSocket, path);

    /// <summary>A named pipe name (Windows).</summary>
    public static ScoutEndpoint UserPipe(string name) => new(ScoutTransport.UserPipe, name);

    /// <summary>An address: https is called, any other scheme is plain http and refused.</summary>
    public static ScoutEndpoint FromUri(Uri uri) =>
        uri.Scheme == Uri.UriSchemeHttps
            ? new(ScoutTransport.Https, uri.GetLeftPart(UriPartial.Authority))
            : new(ScoutTransport.PlainHttp, uri.GetLeftPart(UriPartial.Authority));
}
