namespace D3sk.AgentCli.Runner;

/// <summary>Splits a byte stream into newline-delimited chunks with no per-line ceiling.</summary>
public static class LineReader
{
    private const int ReadChunk = 64 * 1024;

    /// <summary>
    /// Yields each line (newline included; a final unterminated one too). Ends on end of stream,
    /// a broken pipe, cancellation, or <paramref name="deadline"/> running out. Without a
    /// started deadline, <paramref name="hasExited"/> is polled every <paramref name="poll"/>: a
    /// CLI that exited without a result gets the same grace.
    /// </summary>
    public static async IAsyncEnumerable<byte[]> ReadAsync(
        Stream stream,
        TurnDeadline? deadline,
        Func<bool>? hasExited,
        TimeSpan poll,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var buf = new List<byte>();
        var chunk = new byte[ReadChunk];
        Task<int>? pending = null;
        while (true)
        {
            pending ??= ReadOnce(stream, chunk);
            TimeSpan? wait = deadline?.Remaining();
            if (wait is null && hasExited is not null && deadline is not null)
            {
                wait = poll;
            }
            var n = 0;
            var timedOut = false;
            try
            {
                // One read stays outstanding across timeouts: a pipe cannot take two at once.
                n = await (wait is { } w ? pending.WaitAsync(w, ct) : pending.WaitAsync(ct)).ConfigureAwait(false);
                pending = null;
            }
            catch (TimeoutException)
            {
                timedOut = true;
            }
            catch (OperationCanceledException)
            {
                yield break;
            }
            if (timedOut)
            {
                if (KeepPollingAfterTimeout(deadline, hasExited))
                {
                    continue;
                }
                if (buf.Count > 0)
                {
                    yield return buf.ToArray();
                }
                yield break;
            }
            if (n <= 0)
            {
                if (buf.Count > 0)
                {
                    yield return buf.ToArray();
                }
                yield break;
            }
            for (var i = 0; i < n; i++)
            {
                buf.Add(chunk[i]);
                if (chunk[i] == (byte)'\n')
                {
                    yield return buf.ToArray();
                    buf.Clear();
                }
            }
        }
    }

    private static bool KeepPollingAfterTimeout(TurnDeadline? deadline, Func<bool>? hasExited)
    {
        if (deadline is null)
        {
            return false;
        }
        if (!deadline.Started)
        {
            if (hasExited is not null && hasExited())
            {
                deadline.Start();
            }
            return true;
        }
        deadline.Expired = true;
        return false;
    }

    private static async Task<int> ReadOnce(Stream stream, byte[] chunk)
    {
        try
        {
            return await stream.ReadAsync(chunk).ConfigureAwait(false);
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException)
        {
            return 0;
        }
    }
}
