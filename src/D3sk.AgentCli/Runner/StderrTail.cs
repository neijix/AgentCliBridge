namespace D3sk.AgentCli.Runner;

/// <summary>Drains a stderr stream while the turn runs, keeping at most the last 256 KiB.</summary>
public sealed class StderrTail
{
    /// <summary>The most bytes kept.</summary>
    public const int MaxBytes = 256 * 1024;

    private readonly object _gate = new();
    private readonly byte[] _ring = new byte[MaxBytes];
    private int _count;
    private int _head;
    private readonly Task _drain;

    /// <summary>Starts draining <paramref name="stream"/> at once.</summary>
    public StderrTail(Stream stream) => _drain = Task.Run(() => DrainAsync(stream));

    private async Task DrainAsync(Stream stream)
    {
        var chunk = new byte[64 * 1024];
        try
        {
            while (true)
            {
                var n = await stream.ReadAsync(chunk).ConfigureAwait(false);
                if (n == 0)
                {
                    return;
                }
                Append(chunk.AsSpan(0, n));
            }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException)
        {
            // the pipe closed under us: keep what we have
        }
    }

    private void Append(ReadOnlySpan<byte> data)
    {
        lock (_gate)
        {
            if (data.Length >= MaxBytes)
            {
                data[^MaxBytes..].CopyTo(_ring);
                _head = 0;
                _count = MaxBytes;
                return;
            }
            foreach (var b in data)
            {
                var tail = (_head + _count) % MaxBytes;
                _ring[tail] = b;
                if (_count == MaxBytes)
                {
                    _head = (_head + 1) % MaxBytes;
                }
                else
                {
                    _count++;
                }
            }
        }
    }

    /// <summary>What was kept so far, without waiting.</summary>
    public byte[] Snapshot()
    {
        lock (_gate)
        {
            var result = new byte[_count];
            for (var i = 0; i < _count; i++)
            {
                result[i] = _ring[(_head + i) % MaxBytes];
            }
            return result;
        }
    }

    /// <summary>Waits for the stream to end (at most <paramref name="timeout"/>, else no limit), then returns the tail.</summary>
    public async Task<byte[]> ReadAsync(TimeSpan? timeout = null)
    {
        try
        {
            await (timeout is { } t ? _drain.WaitAsync(t) : _drain).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            // a surviving child holds the pipe: return what arrived
        }
        return Snapshot();
    }
}
