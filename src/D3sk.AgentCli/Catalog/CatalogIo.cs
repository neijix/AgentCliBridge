using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace D3sk.AgentCli.Catalog;

/// <summary>What a failed listing or gateway read throws; anything else is a bug and propagates.</summary>
public static class CatalogErrors
{
    /// <summary>Whether <paramref name="ex"/> is a CLI that could not list its models.</summary>
    public static bool IsListFailure(Exception ex) =>
        ex is IOException or InvalidOperationException or Win32Exception or TimeoutException or FormatException or ArgumentException;
}

/// <summary>The two reads a catalog needs from outside: a CLI's <c>models</c> output and a gateway's JSON.</summary>
public static class CatalogIo
{
    /// <summary>A <c>models</c> listing that takes longer than this is abandoned (OpenCode refreshes from the network first).</summary>
    public static readonly TimeSpan ListTimeout = TimeSpan.FromSeconds(45);

    /// <summary>The most a gateway may answer.</summary>
    public const int GatewayMaxBytes = 4 * 1024 * 1024;

    /// <summary>How long a gateway has to answer.</summary>
    public static readonly TimeSpan GatewayTimeout = TimeSpan.FromSeconds(5);

    /// <summary>Runs one <c>&lt;cli&gt; models</c> (no shell); throws when it cannot run or exits non-zero.</summary>
    public static string RunList(IReadOnlyList<string> argv)
    {
        var info = new ProcessStartInfo(argv[0])
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var arg in argv.Skip(1))
        {
            info.ArgumentList.Add(arg);
        }
        using var process = Process.Start(info) ?? throw new InvalidOperationException($"could not start {argv[0]}");
        process.StandardInput.Close();
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(ListTimeout))
        {
            process.Kill(entireProcessTree: true);
            throw new TimeoutException($"{argv[0]} did not answer in {ListTimeout.TotalSeconds:0}s");
        }
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            var tail = (stderr.Result.Length > 0 ? stderr.Result : stdout.Result).Trim().Split('\n')[^1];
            throw new InvalidOperationException($"exit {process.ExitCode}: {tail[..Math.Min(tail.Length, 200)]}");
        }
        return stdout.Result;
    }

    /// <summary>
    /// GETs <paramref name="url"/> as JSON with no credentials, no redirect and at most
    /// <see cref="GatewayMaxBytes"/>. Only http(s) without user info is read. A non-2xx answer is an
    /// <see cref="HttpRequestException"/> with its status; one that never answered has none.
    /// </summary>
    public static JsonNode? FetchJson(string url) => FetchJson(url, null);

    /// <summary>
    /// As <see cref="FetchJson(string)"/>, sending <paramref name="headers"/> too, but only to an https URL:
    /// plain http, loopback included, gets none (a local port may be held by any process).
    /// </summary>
    public static JsonNode? FetchJson(string url, IReadOnlyDictionary<string, string>? headers)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            || uri.UserInfo.Length > 0)
        {
            throw new ArgumentException("only an http(s) URL without credentials is read");
        }
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false, UseProxy = !uri.IsLoopback };
        using var client = new HttpClient(handler) { Timeout = GatewayTimeout };
        using var request = BuildGatewayRequest(uri, headers);
        using var response = client.Send(request, HttpCompletionOption.ResponseHeadersRead);
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"HTTP {(int)response.StatusCode}", null, response.StatusCode);
        }
        using var stream = response.Content.ReadAsStream();
        using var buffer = new MemoryStream();
        var chunk = new byte[16 * 1024];
        int read;
        while ((read = stream.Read(chunk, 0, chunk.Length)) > 0)
        {
            if (buffer.Length + read > GatewayMaxBytes)
            {
                throw new ArgumentException($"answer is over {GatewayMaxBytes} bytes");
            }
            buffer.Write(chunk, 0, read);
        }
        try
        {
            return JsonNode.Parse(buffer.ToArray());
        }
        catch (JsonException ex)
        {
            throw new FormatException("the answer is not JSON", ex);
        }
    }

    /// <summary>
    /// The GET <see cref="FetchJson(string, IReadOnlyDictionary{string, string})"/> sends: <paramref name="headers"/>
    /// only when <paramref name="uri"/> is https, its own <c>Accept</c> and <c>User-Agent</c> winning over given ones.
    /// A header the HTTP stack refuses throws <see cref="ArgumentException"/>.
    /// </summary>
    internal static HttpRequestMessage BuildGatewayRequest(Uri uri, IReadOnlyDictionary<string, string>? headers)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, uri);
        if (uri.Scheme == Uri.UriSchemeHttps && headers is not null)
        {
            foreach (var (name, value) in headers)
            {
                if (string.Equals(name, "Accept", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "User-Agent", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                if (!request.Headers.TryAddWithoutValidation(name, value))
                {
                    request.Dispose();
                    throw new ArgumentException("the HTTP stack refuses a gateway header");
                }
            }
        }
        request.Headers.Accept.ParseAdd("application/json");
        request.Headers.UserAgent.ParseAdd("D3sk.AgentCli");
        return request;
    }
}
