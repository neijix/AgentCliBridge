using System.Text.Json.Nodes;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Tests.WebScout;

public sealed class SettingsArgsTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("settingsargs").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    [Fact]
    public void One_or_no_settings_leave_the_arguments_alone()
    {
        string[] args = ["--model", "x", "--settings", "{\"a\":1}"];

        Assert.Equal(args, SettingsArgs.Merge(args));
        Assert.Equal(["--model", "x"], SettingsArgs.Merge(["--model", "x"]));
    }

    [Fact]
    [Trait("Preserve", "P24")]
    public void Several_settings_fold_into_one_at_the_end_with_the_rule_lists_joined_and_later_keys_winning()
    {
        var file = Path.Combine(_dir, "mine.json");
        File.WriteAllText(file, "{\"permissions\":{\"ask\":[\"Bash(a:*)\"],\"deny\":[\"X\"]},\"model\":\"old\"}");

        var merged = SettingsArgs.Merge(["--settings", file, "--print", "--settings", "{\"permissions\":{\"ask\":[\"Bash(b:*)\",\"Bash(a:*)\"]},\"model\":\"new\"}"]);

        Assert.Equal(["--print", "--settings"], merged[..2]);
        Assert.Equal(3, merged.Count);
        var settings = JsonNode.Parse(merged[2])!;
        Assert.Equal(["Bash(a:*)", "Bash(b:*)"], settings["permissions"]!["ask"]!.AsArray().Select(n => (string)n!));
        Assert.Equal(["X"], settings["permissions"]!["deny"]!.AsArray().Select(n => (string)n!));
        Assert.Equal("new", (string)settings["model"]!);
    }

    [Fact]
    public void A_value_that_cannot_be_read_is_dropped_and_the_rest_still_merge()
    {
        var merged = SettingsArgs.Merge(["--settings", Path.Combine(_dir, "missing.json"), "--settings=" + "{\"a\":1}", "--settings", "{\"b\":2}"]);

        Assert.Equal(["--settings", "{\"a\":1,\"b\":2}"], merged);
    }
}
