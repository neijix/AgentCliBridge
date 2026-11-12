using System.Text;
using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Tests.Status;

[Trait("Preserve", "P38")]
public class ReleaseSourcesTests
{
    [Fact]
    public void Version_outputs_of_every_cli_parse_to_a_bare_version()
    {
        Assert.Equal("2.1.267", ReleaseSources.ParseVersion(StatusFakes.VersionOutput["claude"]));
        Assert.Equal("1.0.87", ReleaseSources.ParseVersion(StatusFakes.VersionOutput["copilot"]));
        Assert.Equal("1.0.40", ReleaseSources.ParseVersion(StatusFakes.VersionOutput["grok"]));
        Assert.Equal("2026.09.18-9a7762b", ReleaseSources.ParseVersion(StatusFakes.VersionOutput["agent"]));
        Assert.Equal("", ReleaseSources.ParseVersion("nothing here"));
        Assert.Equal("", ReleaseSources.ParseVersion(null));
    }

    [Fact]
    public void Newer_compares_numerically_and_unknown_is_neither()
    {
        Assert.True(ReleaseSources.IsOutdated("2.1.267", "2.1.280"));
        Assert.True(ReleaseSources.IsOutdated("2.1.9", "2.1.10"));
        Assert.False(ReleaseSources.IsOutdated("2.1.280", "2.1.280"));
        Assert.False(ReleaseSources.IsOutdated("2.1.281", "2.1.280"));
        Assert.False(ReleaseSources.IsOutdated("2026.09.18-9a7762b", "2026.09.18-ffffff"));
        Assert.True(ReleaseSources.IsOutdated("2.1", "2.1.1"));
        Assert.Null(ReleaseSources.IsOutdated("", "2.1.280"));
        Assert.Null(ReleaseSources.IsOutdated("2.1.280", ""));
    }

    [Fact]
    public void Release_sources_are_the_npm_dist_tags_or_cursors_install_script()
    {
        Assert.Equal("https://registry.npmjs.org/-/package/@anthropic-ai%2Fclaude-code/dist-tags", ReleaseSources.LatestUrl("claude"));
        Assert.Equal("https://registry.npmjs.org/-/package/opencode-ai/dist-tags", ReleaseSources.LatestUrl("opencode"));
        Assert.Equal(ReleaseSources.CursorInstallUrl, ReleaseSources.LatestUrl("agent"));
        Assert.Equal("", ReleaseSources.LatestUrl("agy"));
        Assert.Equal("2.1.280", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("""{"stable":"2.1.267","latest":"2.1.280","next":"2.1.280"}""")));
        Assert.Equal("", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("not json")));
        Assert.Equal("", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("""["latest"]""")));
        Assert.Equal("", ReleaseSources.ParseLatest("claude", [0xFF, 0xFE, 0x7B]));
        Assert.Equal("2026.09.18-9a7762b", ReleaseSources.ParseLatest("agent", StatusFakes.CursorScript));
        Assert.Equal("", ReleaseSources.ParseLatest("agent", Encoding.UTF8.GetBytes("#!/bin/bash\necho no build here\n")));
    }

    [Theory]
    [InlineData("claude")]
    [InlineData("gemini")]
    [InlineData("copilot")]
    [InlineData("grok")]
    [InlineData("opencode")]
    public void Every_npm_published_cli_has_its_package(string command) =>
        Assert.StartsWith("https://registry.npmjs.org/-/package/", ReleaseSources.LatestUrl(command), StringComparison.Ordinal);

    [Fact]
    public void A_homebrew_formula_is_named_by_its_cellar_folder_only()
    {
        Assert.Equal("opencode", ReleaseSources.HomebrewFormula("/opt/homebrew/Cellar/opencode/1.18.30_2/bin/opencode"));
        Assert.Equal("", ReleaseSources.HomebrewFormula("/usr/local/lib/node_modules/opencode-ai/bin/opencode"));
        Assert.Equal("", ReleaseSources.HomebrewFormula("/opt/homebrew/Cellar/--evil/1/bin/x"));
        Assert.Equal("", ReleaseSources.HomebrewFormula("/opt/homebrew/Cellar"));
        Assert.Equal("", ReleaseSources.HomebrewFormula(""));
        Assert.Equal("https://formulae.brew.sh/api/formula/opencode.json", ReleaseSources.LatestUrl("opencode", "opencode"));
        Assert.Equal("", ReleaseSources.ParseLatest("opencode", Encoding.UTF8.GetBytes("not json"), "opencode"));
        Assert.Equal("1.18.30", ReleaseSources.ParseLatest("opencode", Encoding.UTF8.GetBytes("""{"name":"opencode","versions":{"stable":"1.18.30","head":null}}"""), "opencode"));
    }

    [Theory]
    [InlineData("claude-code@latest", true)]
    [InlineData("claude-code", true)]
    [InlineData("other", false)]
    public void A_claude_cask_binary_is_the_claude_file_in_its_caskroom_folder(string cask, bool expected)
    {
        Assert.Equal(expected, ReleaseSources.IsClaudeCaskBinary($"/opt/homebrew/Caskroom/{cask}/2.1.267/claude"));
        Assert.False(ReleaseSources.IsClaudeCaskBinary($"/opt/homebrew/Caskroom/{cask}/2.1.267/other"));
        Assert.False(ReleaseSources.IsClaudeCaskBinary(""));
        Assert.False(ReleaseSources.IsClaudeCaskBinary("Caskroom/claude-code/1/claude"));
    }

    [Fact]
    public void Anthropics_download_answers_a_plain_version_or_nothing()
    {
        Assert.Equal("2.1.292", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("2.1.292\n"), isClaudeCask: true));
        Assert.Equal("", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("<html>"), isClaudeCask: true));
        Assert.Equal("", ReleaseSources.ParseLatest("claude", Encoding.UTF8.GetBytes("2.1.292-beta"), isClaudeCask: true));
    }
}
