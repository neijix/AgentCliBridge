namespace D3sk.AgentCli.WebScout;

/// <summary>Where the D3SKWEBSCOUT checkout is, which port its shell client calls and where its user-only socket lives.</summary>
public sealed record ScoutLocation(string Checkout, int Port, string SocketPath);

/// <summary>
/// Finds D3SKWEBSCOUT the way the Python app does: <c>$D3SKWEBSCOUT_DIR</c> only when set, else
/// <c>D3SKWEBSCOUT</c> under <c>$AI_CODE_ROOT</c>, <c>~/Code</c> and <c>~/CODE</c>; a candidate counts
/// when it holds its own venv python and <c>src/d3skwebscout</c>.
/// </summary>
public static class ScoutLocator
{
    /// <summary>The checkout's folder name.</summary>
    public const string CheckoutName = "D3SKWEBSCOUT";
    /// <summary>The scout's shell command and Python module.</summary>
    public const string Module = "d3skwebscout";
    /// <summary>The port the scout's client calls when nothing says otherwise.</summary>
    public const int DefaultPort = 4820;
    /// <summary>Environment variable that names the scout's user-only socket.</summary>
    public const string SocketEnv = "D3SKWEBSCOUT_SOCKET";
    /// <summary>The socket's name under the checkout's <c>data</c> folder when the variable is unset.</summary>
    public const string SocketFile = "webscout.sock";

    /// <summary>The venv's python inside <paramref name="checkout"/>.</summary>
    public static string VenvPython(string checkout, bool? isWindows = null) =>
        (isWindows ?? OperatingSystem.IsWindows())
            ? Path.Combine(checkout, ".venv", "Scripts", "python.exe")
            : Path.Combine(checkout, ".venv", "bin", "python");

    /// <summary>The folders that may hold the checkout, most specific first.</summary>
    public static IReadOnlyList<string> DefaultCandidates(Func<string, string?>? env = null, string? home = null)
    {
        env ??= Environment.GetEnvironmentVariable;
        var explicitDir = (env("D3SKWEBSCOUT_DIR") ?? "").Trim();
        if (explicitDir.Length > 0)
        {
            return [ExpandHome(explicitDir, home)];
        }
        var userHome = home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var bases = new List<string>();
        var root = (env("AI_CODE_ROOT") ?? "").Trim();
        if (root.Length > 0)
        {
            bases.Add(ExpandHome(root, home));
        }
        bases.Add(Path.Combine(userHome, "Code"));
        bases.Add(Path.Combine(userHome, "CODE"));
        return [.. bases.Select(b => Path.Combine(b, CheckoutName))];
    }

    /// <summary>The first installed checkout (symlinks resolved), or null.</summary>
    public static string? FindCheckout(IEnumerable<string> candidates)
    {
        foreach (var candidate in candidates)
        {
            if (File.Exists(VenvPython(candidate)) && Directory.Exists(Path.Combine(candidate, "src", Module)))
            {
                var full = Path.GetFullPath(candidate);
                return Directory.ResolveLinkTarget(full, returnFinalTarget: true)?.FullName ?? full;
            }
        }
        return null;
    }

    /// <summary>
    /// The port the shell client calls: <c>WEBSCOUT_PORT</c>, else <c>PORT</c> from the checkout's
    /// <c>.env</c>, else 4820. A value that is not a number is 4820.
    /// </summary>
    public static int ClientPort(string checkout, Func<string, string?>? env = null)
    {
        env ??= Environment.GetEnvironmentVariable;
        var raw = (env("WEBSCOUT_PORT") ?? "").Trim();
        if (raw.Length == 0)
        {
            raw = DotenvValue(Path.Combine(checkout, ".env"), "PORT");
        }
        return int.TryParse(raw, out var port) && port is > 0 and < 65536 ? port : DefaultPort;
    }

    /// <summary>The checkout, port and socket path, or null when no checkout is installed.</summary>
    public static ScoutLocation? Locate(Func<string, string?>? env = null, string? home = null)
    {
        env ??= Environment.GetEnvironmentVariable;
        var checkout = FindCheckout(DefaultCandidates(env, home));
        if (checkout is null)
        {
            return null;
        }
        var socket = (env(SocketEnv) ?? "").Trim();
        return new ScoutLocation(
            checkout,
            ClientPort(checkout, env),
            socket.Length > 0 ? ExpandHome(socket, home) : Path.Combine(checkout, "data", SocketFile));
    }

    /// <summary>
    /// Where to call: the user-only socket when it exists, else the plain port a scout that is not
    /// upgraded still listens on (the client turns that into a "service needs update" result).
    /// </summary>
    public static ScoutEndpoint EndpointFor(ScoutLocation location) =>
        File.Exists(location.SocketPath)
            ? ScoutEndpoint.UserSocket(location.SocketPath)
            : ScoutEndpoint.FromUri(new Uri($"http://127.0.0.1:{location.Port}"));

    private static string ExpandHome(string path, string? home)
    {
        if (path != "~" && !path.StartsWith("~/", StringComparison.Ordinal))
        {
            return path;
        }
        var userHome = home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return Path.Combine(userHome, path.TrimStart('~').TrimStart('/'));
    }

    private static string DotenvValue(string file, string key)
    {
        try
        {
            foreach (var line in File.ReadLines(file))
            {
                var text = line.Trim();
                var eq = text.IndexOf('=');
                if (text.Length == 0 || text[0] == '#' || eq <= 0)
                {
                    continue;
                }
                var name = text[..eq].Trim();
                if (name.StartsWith("export ", StringComparison.Ordinal))
                {
                    name = name[7..].Trim();
                }
                if (name == key)
                {
                    return text[(eq + 1)..].Trim().Trim('"', '\'');
                }
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
        return "";
    }
}
