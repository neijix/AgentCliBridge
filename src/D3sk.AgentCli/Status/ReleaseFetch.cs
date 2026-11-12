namespace D3sk.AgentCli.Status;

/// <summary>One size-limited GET of a small document from a fixed release source.</summary>
public static class ReleaseFetch
{
    /// <summary>The most a release source may answer: dist-tags are ~100 bytes and Cursor's script ~6 KB.</summary>
    public const int MaxBytes = 512 * 1024;

    /// <summary>How long a release source has to answer.</summary>
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(10);

    /// <summary>
    /// GETs <paramref name="url"/>: http(s) only, no credentials in the URL, no redirect (the bytes
    /// come from the host that was named), at most <see cref="MaxBytes"/>. A non-2xx answer is an
    /// <see cref="HttpRequestException"/>; a longer body an <see cref="ArgumentException"/>.
    /// </summary>
    public static async Task<byte[]> GetAsync(string url, CancellationToken ct)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            || uri.UserInfo.Length > 0)
        {
            throw new ArgumentException("only an http(s) URL without credentials is read");
        }
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false, UseProxy = !uri.IsLoopback };
        using var client = new HttpClient(handler) { Timeout = Timeout };
        using var request = new HttpRequestMessage(HttpMethod.Get, uri);
        request.Headers.Accept.ParseAdd("application/json, text/plain;q=0.5");
        request.Headers.UserAgent.ParseAdd("AgentCliBridge");
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"HTTP {(int)response.StatusCode}", null, response.StatusCode);
        }
        await using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var buffer = new MemoryStream();
        var chunk = new byte[16 * 1024];
        int read;
        while ((read = await stream.ReadAsync(chunk, ct).ConfigureAwait(false)) > 0)
        {
            if (buffer.Length + read > MaxBytes)
            {
                throw new ArgumentException($"answer is over {MaxBytes} bytes");
            }
            buffer.Write(chunk, 0, read);
        }
        return buffer.ToArray();
    }
}
