using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

public sealed class ClaudeReleaseTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("cask").FullName;

    public void Dispose() => Directory.Delete(_root, recursive: true);

    private string CaskFile()
    {
        var dir = Path.Combine(_root, "Caskroom", "claude-code@latest", "2.1.280");
        Directory.CreateDirectory(dir);
        var file = Path.Combine(dir, "claude");
        File.WriteAllText(file, "old");
        return file;
    }

    private static byte[] Elf(long size)
    {
        var body = new byte[size];
        "\x7fELF"u8.CopyTo(body);
        return body;
    }

    private static (ClaudeRelease Release, FakeHttp Http, FakeRunner Runner) Rig()
    {
        var http = new FakeHttp();
        var runner = new FakeRunner();
        return (new ClaudeRelease(new ScriptDownloader(http.Client()), runner), http, runner);
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public void The_release_url_is_Anthropics_and_rejects_anything_else()
    {
        Assert.Equal("https://downloads.claude.ai/claude-code-releases/2.1.281/darwin-arm64/claude", ClaudeRelease.Url("2.1.281", "darwin", "arm64"));
        Assert.Equal("https://downloads.claude.ai/claude-code-releases/2.1.281/linux-x64/claude", ClaudeRelease.Url("2.1.281", "linux", "x86_64"));
        foreach (var version in new[] { "", "latest", "2.1.x", "../2.1.1", "2..1" })
        {
            Assert.Throws<InstallStepException>(() => ClaudeRelease.Url(version, "linux", "x64"));
        }
        Assert.Throws<InstallStepException>(() => ClaudeRelease.Url("2.1.281", "windows", "x64"));
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task Only_the_latest_cask_file_itself_may_be_replaced()
    {
        var (release, http, _) = Rig();
        var stray = Path.Combine(_root, "claude");
        File.WriteAllText(stray, "mine");
        var outcome = await release.InstallPublishedAsync(stray, "2.1.281", "linux", "x64", TestContext.Current.CancellationToken);
        Assert.Equal("plan", outcome.Step);
        Assert.Equal("mine", File.ReadAllText(stray));
        Assert.Empty(http.Requests);
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_download_that_is_not_an_executable_leaves_the_cask_binary_in_place()
    {
        var (release, http, _) = Rig();
        var file = CaskFile();
        var body = new byte[ClaudeRelease.MinBytes];  // right size, wrong header
        http.Bodies[ClaudeRelease.Url("2.1.281", "linux", "x64")] = body;
        var outcome = await release.InstallPublishedAsync(file, "2.1.281", "linux", "x64", TestContext.Current.CancellationToken);
        Assert.Equal("verify", outcome.Step);
        Assert.Equal("old", File.ReadAllText(file));
        Assert.Single(Directory.GetFiles(Path.GetDirectoryName(file)!));  // the temp download is gone
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_binary_of_the_wrong_size_is_refused()
    {
        var (release, http, _) = Rig();
        var file = CaskFile();
        http.Bodies[ClaudeRelease.Url("2.1.281", "linux", "x64")] = Elf(1024);
        var outcome = await release.InstallPublishedAsync(file, "2.1.281", "linux", "x64", TestContext.Current.CancellationToken);
        Assert.Equal("download", outcome.Step);
        Assert.Equal("old", File.ReadAllText(file));
    }

    [Fact]
    [Trait("Preserve", "P38")]
    public async Task A_good_download_replaces_only_the_cask_file()
    {
        var (release, http, runner) = Rig();
        var file = CaskFile();
        http.Bodies[ClaudeRelease.Url("2.1.281", "linux", "x64")] = Elf(ClaudeRelease.MinBytes);
        var outcome = await release.InstallPublishedAsync(file, "2.1.281", "linux", "x64", TestContext.Current.CancellationToken);
        Assert.True(outcome.Ok, outcome.Message);
        Assert.Contains("2.1.281", outcome.Output);
        Assert.Equal(ClaudeRelease.MinBytes, new FileInfo(file).Length);
        Assert.Single(Directory.GetFiles(Path.GetDirectoryName(file)!));
        Assert.Empty(runner.Ran);  // Linux has no signature tool to run
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_macOS_binary_not_signed_by_Anthropic_is_refused()
    {
        var (release, http, runner) = Rig();
        var file = CaskFile();
        var body = new byte[ClaudeRelease.MinBytes];
        new byte[] { 0xcf, 0xfa, 0xed, 0xfe }.CopyTo(body, 0);
        http.Bodies[ClaudeRelease.Url("2.1.281", "darwin", "arm64")] = body;
        runner.Answer = argv => argv[1] == "--verify" ? new ProcessResult(0, "") : new ProcessResult(0, "Identifier=com.other.app\nTeamIdentifier=ABCDE12345");
        var outcome = await release.InstallPublishedAsync(file, "2.1.281", "darwin", "arm64", TestContext.Current.CancellationToken);
        Assert.Equal("verify", outcome.Step);
        Assert.Contains("not signed by Anthropic", outcome.Message);
        Assert.Equal("old", File.ReadAllText(file));
    }
}
