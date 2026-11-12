using System.Text;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Tests.Output.Common;

/// <summary>
/// Replays a frozen <c>tests/streams/&lt;command&gt;__&lt;scenario&gt;.jsonl</c> capture through one parser and
/// compares its events with the capture's <c>.expected.jsonl</c>, written by the Python
/// <c>tests/test_stream_contracts.py</c>. Each event is compared as the Python record: its class name
/// under <c>event</c>, then its fields in snake case (<c>ToolResult.raw</c> only when not empty). The
/// expected files end with the <c>Completed</c> the host adds from the exit code (row 37), which a
/// parser never yields, so it is left out here. Every parser row (30 to 36) uses this one helper.
/// </summary>
internal static class StreamCaptures
{
    /// <summary>Lines any CLI might print that are valid JSON but not an object; a parser skips them.</summary>
    public static readonly string[] NotObjects = ["null", "42", "[]", "\"text\"", "true"];

    /// <summary>The frozen captures folder.</summary>
    public static string Folder { get; } = Path.Combine(FindRoot(), "tests", "streams");

    /// <summary>The raw stdout of one capture, e.g. <c>agent__thinking_tools_text</c>.</summary>
    public static string Capture(string name) => File.ReadAllText(Path.Combine(Folder, name + ".jsonl"), Encoding.UTF8);

    /// <summary>The expected records of one capture, without the host's trailing <c>Completed</c>.</summary>
    public static List<string> Expected(string name)
    {
        var records = File.ReadAllLines(Path.Combine(Folder, name + ".expected.jsonl"), Encoding.UTF8)
            .Where(line => line.Length > 0)
            .Select(line => JsonNode.Parse(line)!.ToJsonString())
            .ToList();
        if (records.Count > 0 && JsonNode.Parse(records[^1])!["event"]?.GetValue<string>() == "Completed")
        {
            records.RemoveAt(records.Count - 1);
        }

        return records;
    }

    /// <summary>Feeds <paramref name="stdout"/> to <paramref name="parser"/> line by line and returns its events as records.</summary>
    public static async Task<List<string>> ParseAsync(IOutputParser parser, string stdout, CancellationToken cancellationToken)
    {
        var records = new List<string>();
        await foreach (var streamEvent in parser.ParseAsync(Lines(stdout), cancellationToken))
        {
            records.Add(Record(streamEvent).ToJsonString());
        }

        return records;
    }

    /// <summary>Asserts that the capture yields exactly its expected events.</summary>
    public static async Task AssertReplaysAsync(IOutputParser parser, string name, CancellationToken cancellationToken) =>
        Assert.Equal(Expected(name), await ParseAsync(parser, Capture(name), cancellationToken));

    /// <summary>
    /// Asserts that <paramref name="junk"/> lines, put before and after the capture's first line, change
    /// nothing (the Python <c>test_a_line_that_is_not_the_expected_object_changes_nothing</c>).
    /// </summary>
    public static async Task AssertJunkChangesNothingAsync(IOutputParser parser, string name, IEnumerable<string> junk, CancellationToken cancellationToken)
    {
        var lines = Capture(name).Split('\n').Where(line => line.Length > 0).ToList();
        var junkLines = junk.ToList();
        var noisy = string.Join('\n', junkLines.Concat(lines.Take(1)).Concat(junkLines).Concat(lines.Skip(1))) + "\n";
        Assert.Equal(Expected(name), await ParseAsync(parser, noisy, cancellationToken));
    }

    /// <summary>One event as the Python record (<c>{"event": ClassName, field: value, …}</c>).</summary>
    public static JsonObject Record(StreamEvent streamEvent)
    {
        var record = new JsonObject { ["event"] = streamEvent.GetType().Name };
        foreach (var property in streamEvent.GetType().GetProperties())
        {
            if (property.Name == "EqualityContract")
            {
                continue;
            }

            var value = property.GetValue(streamEvent);
            if (streamEvent is ToolResult && property.Name == nameof(ToolResult.Raw) && value is "")
            {
                continue;
            }

            record[SnakeCase(property.Name)] = value switch
            {
                null => null,
                JsonNode node => node.DeepClone(),
                IEnumerable<string> list when value is not string => new JsonArray(list.Select(item => (JsonNode?)item).ToArray()),
                _ => JsonValue.Create(value),
            };
        }

        return record;
    }

    private static string SnakeCase(string name)
    {
        if (name == nameof(Completed.ReturnCode))
        {
            return "returncode";
        }

        var text = new StringBuilder();
        foreach (var c in name)
        {
            if (char.IsUpper(c) && text.Length > 0)
            {
                text.Append('_');
            }

            text.Append(char.ToLowerInvariant(c));
        }

        return text.ToString();
    }

    private static async IAsyncEnumerable<ChildLine> Lines(string stdout)
    {
        foreach (var line in stdout.Split('\n'))
        {
            yield return new ChildLine(Encoding.UTF8.GetBytes(line));
        }

        await Task.CompletedTask;
    }

    private static string FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "global.json")))
        {
            dir = dir.Parent;
        }

        return dir?.FullName ?? throw new InvalidOperationException("repo root (global.json) not found");
    }
}
