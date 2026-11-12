using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Runner;

public class StderrTailTests
{
    [Fact]
    public async Task Keeps_only_the_last_256KiB()
    {
        var data = new byte[StderrTail.MaxBytes * 2 + 123];
        for (var i = 0; i < data.Length; i++)
        {
            data[i] = (byte)(i % 251);
        }
        var tail = await new StderrTail(new MemoryStream(data)).ReadAsync();
        Assert.Equal(StderrTail.MaxBytes, tail.Length);
        Assert.Equal(data[^StderrTail.MaxBytes..], tail);
    }

    [Fact]
    public async Task Small_writes_across_the_ring_keep_order()
    {
        var data = new byte[StderrTail.MaxBytes + 1000];
        new Random(1).NextBytes(data);
        var tail = await new StderrTail(new ChunkedStream(data, 777)).ReadAsync();
        Assert.Equal(data[^StderrTail.MaxBytes..], tail);
    }

    private sealed class ChunkedStream(byte[] data, int chunk) : MemoryStream(data)
    {
        public override int Read(Span<byte> buffer) => base.Read(buffer[..Math.Min(buffer.Length, chunk)]);

        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken ct = default)
            => ValueTask.FromResult(Read(buffer.Span));
    }
}
