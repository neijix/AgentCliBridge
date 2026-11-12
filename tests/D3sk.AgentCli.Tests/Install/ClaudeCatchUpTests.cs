using System.Text;
using D3sk.AgentCli.Install;
using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Tests.Install;

public sealed class ClaudeCatchUpTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("catchup").FullName;

    public void Dispose() => Directory.Delete(_root, recursive: true);

    private string CaskFile()
    {
        var dir = Path.Combine(_root, "Caskroom", "claude-code@latest", "2.1.280");
        Directory.CreateDirectory(dir);
        var file = Path.Combine(dir, "claude");
        File.WriteAllText(file, "old");
        return file;
    }

    private static (ClaudeCatchUp CatchUp, FakeHttp Http) Rig(string? published)
    {
        var http = new FakeHttp();
        if (published is not null)
        {
            http.Bodies[ReleaseSources.ClaudeReleaseLatestUrl] = Encoding.UTF8.GetBytes(published);
        }
        var client = http.Client();
        var catchUp = new ClaudeCatchUp(
            new ClaudeRelease(new ScriptDownloader(client), new FakeRunner()),
            async (url, ct) => await client.GetByteArrayAsync(url, ct));
        return (catchUp, http);
    }

    private static byte[] Elf()
    {
        var body = new byte[ClaudeRelease.MinBytes];
        "\x7fELF"u8.CopyTo(body);
        return body;
    }

    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task Nothing_is_done_when_npm_is_not_ahead_or_the_binary_is_not_the_latest_cask_file()
    {
        var (catchUp, http) = Rig("2.1.282");

        Assert.Equal(new CatchUpResult(0, ""), await catchUp.AfterUpgradeAsync(CaskFile(), "2.1.280", "2.1.280", Ct, "linux", "x64"));
        Assert.Equal(new CatchUpResult(0, ""), await catchUp.AfterUpgradeAsync(Path.Combine(_root, "claude"), "2.1.280", "2.1.282", Ct, "linux", "x64"));
        Assert.Empty(http.Requests);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task A_cask_behind_a_newer_published_build_is_replaced_by_it()
    {
        var (catchUp, http) = Rig("2.1.282\n");
        var file = CaskFile();
        http.Bodies[ClaudeRelease.Url("2.1.282", "linux", "x64")] = Elf();

        var result = await catchUp.AfterUpgradeAsync(file, "2.1.280", "2.1.282", Ct, "linux", "x64");

        Assert.Equal(0, result.Code);
        Assert.Contains("2.1.282", result.Note);
        Assert.NotEqual("old", File.ReadAllText(file));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task When_Anthropic_serves_nothing_newer_the_update_the_desk_promised_is_reported_as_not_possible()
    {
        var (catchUp, _) = Rig("2.1.280");

        var result = await catchUp.AfterUpgradeAsync(CaskFile(), "2.1.280", "2.1.282", Ct, "linux", "x64");

        Assert.Equal(1, result.Code);
        Assert.Contains("npm advertises 2.1.282", result.Note);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task An_unreadable_or_nameless_release_source_is_a_failure_with_its_reason()
    {
        var down = await Rig(null).CatchUp.AfterUpgradeAsync(CaskFile(), "2.1.280", "2.1.282", Ct, "linux", "x64");
        var nameless = await Rig("<html>nope</html>").CatchUp.AfterUpgradeAsync(CaskFile(), "2.1.280", "2.1.282", Ct, "linux", "x64");

        Assert.Equal(1, down.Code);
        Assert.StartsWith("Homebrew left Claude Code at 2.1.280.", down.Note, StringComparison.Ordinal);
        Assert.Equal(1, nameless.Code);
        Assert.Contains("did not name a version", nameless.Note);
    }

    [Fact]
    public void The_status_checks_and_the_install_plans_share_one_npm_package_table() =>
        Assert.Same(ReleaseSources.NpmPackages, UpdatePlans.NpmPackages);
}
