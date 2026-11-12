using System.Text;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Runner;

public class LineReaderTests
{
    private static async Task<List<string>> Lines(Stream s)
    {
        var all = new List<string>();
        await foreach (var l in LineReader.ReadAsync(s, null, null, TimeSpan.FromSeconds(1)))
        {
            all.Add(Encoding.UTF8.GetString(l));
        }
        return all;
    }

    [Fact]
    public async Task Splits_on_newlines_and_keeps_an_unterminated_tail()
    {
        Assert.Equal(["a\n", "\n", "b\n", "c"], await Lines(new MemoryStream("a\n\nb\nc"u8.ToArray())));
    }

    [Fact]
    public async Task A_line_of_a_megabyte_is_one_line()
    {
        var big = new string('x', 1_000_000) + "\n";
        var lines = await Lines(new MemoryStream(Encoding.UTF8.GetBytes(big)));
        Assert.Equal(big, Assert.Single(lines));
    }

    [Fact]
    public async Task Empty_input_yields_nothing()
    {
        Assert.Empty(await Lines(new MemoryStream()));
    }
}
