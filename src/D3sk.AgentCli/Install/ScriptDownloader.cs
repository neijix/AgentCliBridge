using System.Security.Cryptography;

namespace D3sk.AgentCli.Install;

/// <summary>
/// Saves a vendor's file to disk and checks it. This is what replaces <c>curl … | bash</c>: nothing
/// runs before the whole file is on disk, under its size cap, and (when the vendor publishes a
/// checksum) hashing to it.
/// </summary>
public sealed class ScriptDownloader(HttpClient http)
{
    /// <summary>The most an install script may weigh; real ones are a few tens of KB.</summary>
    public const long MaxScriptBytes = 1024 * 1024;

    private const long MaxChecksumBytes = 64 * 1024;

    /// <summary>Save <paramref name="script"/> into <paramref name="folder"/> (new and empty) and check it; returns the file path.</summary>
    /// <exception cref="InstallStepException">The download or the checksum failed.</exception>
    public async Task<string> FetchAsync(ScriptSource script, string folder, CancellationToken ct)
    {
        var path = Path.Combine(folder, script.FileName);
        await SaveAsync(script.Url, path, MaxScriptBytes, 1, ct).ConfigureAwait(false);
        if (script.ChecksumUrl is { } checksumUrl)
        {
            var listing = Path.Combine(folder, script.FileName + ".sha256");
            await SaveAsync(checksumUrl, listing, MaxChecksumBytes, 1, ct).ConfigureAwait(false);
            await VerifyAsync(path, await File.ReadAllTextAsync(listing, ct).ConfigureAwait(false), script.FileName).ConfigureAwait(false);
        }
        return path;
    }

    /// <summary>Stream <paramref name="url"/> to <paramref name="path"/>: https only, at most <paramref name="maxBytes"/>.</summary>
    /// <exception cref="InstallStepException">Not https, refused, too large or too small, or the network failed.</exception>
    public async Task<long> SaveAsync(string url, string path, long maxBytes, long minBytes, CancellationToken ct)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
        {
            throw new InstallStepException("download", $"refusing a download that is not https: {url}");
        }
        try
        {
            using var response = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();
            if (response.RequestMessage?.RequestUri is { Scheme: not "https" })
            {
                throw new InstallStepException("download", "refusing a redirect away from https");
            }
            if (response.Content.Headers.ContentLength is { } announced && (announced > maxBytes || announced < minBytes))
            {
                throw new InstallStepException("download", $"{uri.Host} announced {announced} bytes, which is not what was expected");
            }
            long total = 0;
            var options = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
            if (!OperatingSystem.IsWindows())
            {
                options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
            }
            await using (var input = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false))
            await using (var output = new FileStream(path, options))
            {
                var buffer = new byte[81920];
                int read;
                while ((read = await input.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
                {
                    total += read;
                    if (total > maxBytes)
                    {
                        throw new InstallStepException("download", $"{uri.Host} sent more than {maxBytes} bytes");
                    }
                    await output.WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
                }
            }
            return total >= minBytes ? total : throw new InstallStepException("download", $"{uri.Host} sent only {total} bytes");
        }
        catch (Exception ex) when (ex is HttpRequestException or IOException or TaskCanceledException && !ct.IsCancellationRequested)
        {
            throw new InstallStepException("download", $"could not download {uri.Host}: {ex.Message}");
        }
    }

    private static async Task VerifyAsync(string path, string listing, string fileName)
    {
        var expected = ExpectedHash(listing, fileName)
            ?? throw new InstallStepException("checksum", "the published checksum file does not hold a SHA-256 for the script");
        string actual;
        await using (var stream = File.OpenRead(path))
        {
            actual = Convert.ToHexStringLower(await SHA256.HashDataAsync(stream).ConfigureAwait(false));
        }
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
        {
            throw new InstallStepException("checksum", $"the script's SHA-256 is {actual}, the vendor publishes {expected}; nothing was run");
        }
    }

    /// <summary>The SHA-256 a vendor's checksum file names: a bare hash, or <c>hash  name</c> lines.</summary>
    public static string? ExpectedHash(string listing, string fileName)
    {
        string? bare = null;
        foreach (var line in listing.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var fields = line.Split([' ', '\t', '*'], StringSplitOptions.RemoveEmptyEntries);
            if (fields.Length == 0 || fields[0].Length != 64 || !fields[0].All(Uri.IsHexDigit))
            {
                continue;
            }
            if (fields.Length == 1)
            {
                bare ??= fields[0].ToLowerInvariant();
            }
            else if (fields[^1] == fileName)
            {
                return fields[0].ToLowerInvariant();
            }
        }
        return bare;
    }
}

/// <summary>One step of an install failed; <see cref="Step"/> names it.</summary>
public sealed class InstallStepException(string step, string message) : Exception(message)
{
    /// <summary>The step that failed (an <see cref="InstallOutcome.Step"/> value).</summary>
    public string Step { get; } = step;
}
