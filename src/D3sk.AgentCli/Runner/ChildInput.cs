using System.Text;
using System.Text.Json;

namespace D3sk.AgentCli.Runner;

/// <summary>
/// The writable stdin of a live turn. Created by the host, bound by the runner once the child
/// started and closed when the turn ends; a write that cannot happen returns false.
/// </summary>
public sealed class ChildInput
{
    private readonly object _gate = new();
    private Stream? _stream;
    private bool _closed;
    private Action? _onBound;

    /// <summary>Writes one JSON object and a newline; false when the child is gone or the turn ended.</summary>
    public bool WriteJsonLine<T>(T payload, System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> info)
        => WriteLine(JsonSerializer.Serialize(payload, info));

    /// <summary>Writes one line of text and a newline; false when it cannot be delivered.</summary>
    public bool WriteLine(string line)
    {
        lock (_gate)
        {
            if (_stream is null || _closed)
            {
                return false;
            }
            try
            {
                var bytes = Encoding.UTF8.GetBytes(line + "\n");
                _stream.Write(bytes);
                _stream.Flush();
                return true;
            }
            catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException)
            {
                return false;
            }
        }
    }

    /// <summary>Runs <paramref name="hook"/> once the child's stdin is bound (at once when it already is); the hook may write.</summary>
    internal void WhenBound(Action hook)
    {
        lock (_gate)
        {
            if (_stream is null)
            {
                _onBound = hook;
                return;
            }
        }
        hook();
    }

    internal void Bind(Stream stream)
    {
        Action? hook;
        lock (_gate)
        {
            _stream = stream;
            hook = _onBound;
            _onBound = null;
        }
        hook?.Invoke();
    }

    internal void Close()
    {
        lock (_gate)
        {
            _closed = true;
            try
            {
                _stream?.Dispose();
            }
            catch (Exception e) when (e is IOException or ObjectDisposedException)
            {
                // the child already closed its end
            }
        }
    }
}
