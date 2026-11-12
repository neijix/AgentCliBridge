using System.Text;
using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Tests.Status;

[Trait("Preserve", "P38")]
public class CliStatusTests
{
    private static CancellationToken Ct => TestContext.Current.CancellationToken;

    private static async Task<CliStatusRow> OneAsync(CliStatus status, AgentRef agent, bool force = false) =>
        Assert.Single((await status.StatusAsync([agent], force, Ct)).Agents);

    [Fact]
    public async Task Status_rows_say_installed_latest_and_whether_behind()
    {
        var fakes = new StatusFakes();
        var report = await fakes.Status().StatusAsync(StatusFakes.Agents, ct: Ct);
        Assert.Equal(1_000.0, report.CheckedAt);
        var rows = report.Agents.ToDictionary(row => row.Command);
        Assert.Equal(new CliStatusRow("claude", "Claude Code", "2.1.267", "2.1.280", true, "npm", "", true, true), rows["claude"]);
        Assert.Equal("2026.09.18-9a7762b", rows["agent"].Installed);
        Assert.Equal("2026.09.18-9a7762b", rows["agent"].Latest);
        Assert.False(rows["agent"].IsOutdated);
        Assert.Equal("cursor", rows["agent"].Source);
        Assert.False(rows["agent"].NeedsCode);
        Assert.Equal(new CliStatusRow("agy", "Google Antigravity", "1.2.8", "", null, "", "", false, false), rows["agy"]);
        Assert.True(rows["opencode"].IsOutdated);
        Assert.True(rows["opencode"].NeedsCode);
        Assert.DoesNotContain(fakes.Fetches, url => url.Contains("agy", StringComparison.Ordinal));
    }

    [Fact]
    public async Task A_missing_binary_or_a_dead_registry_is_a_row_with_its_reason_never_an_error()
    {
        var fakes = new StatusFakes { Latest = [] };
        fakes.Broken.Add("claude");
        var rows = (await fakes.Status().StatusAsync(StatusFakes.Agents, ct: Ct)).Agents.ToDictionary(row => row.Command);
        Assert.Equal("", rows["claude"].Installed);
        Assert.Null(rows["claude"].IsOutdated);
        Assert.Contains("not found", rows["claude"].Error, StringComparison.Ordinal);
        Assert.Equal("1.18.30", rows["opencode"].Installed);
        Assert.Equal("", rows["opencode"].Latest);
        Assert.Null(rows["opencode"].IsOutdated);
        Assert.Equal("registry down", rows["opencode"].Error);
    }

    [Fact]
    public async Task A_stuck_cli_is_reported_not_waited_for_again()
    {
        var fakes = new StatusFakes();
        var sources = fakes.Sources with { RunVersion = (_, _, _) => throw new TimeoutException("claude timed out after 20 seconds") };
        var status = new CliStatus(sources);
        var first = await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal("", first.Installed);
        Assert.Contains("timed out", first.Error, StringComparison.Ordinal);
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Single(fakes.Fetches, ReleaseSources.LatestUrl("claude"));
    }

    [Fact]
    public async Task A_version_output_with_no_version_is_a_row_with_that_reason()
    {
        var sources = new StatusFakes().Sources with { RunVersion = (_, _, _) => Task.FromResult("usage: claude [options]") };
        Assert.Equal("no version in the output", (await OneAsync(new CliStatus(sources), StatusFakes.Agents[0])).Error);
    }

    [Fact]
    public async Task Checks_are_cached_and_expire_on_their_own_clocks()
    {
        var fakes = new StatusFakes();
        var status = fakes.Status();
        await OneAsync(status, StatusFakes.Agents[0]);
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal(["claude"], fakes.Runs);
        Assert.Single(fakes.Fetches);
        fakes.Now += CliStatus.InstalledTtl + 1;
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal(["claude", "claude"], fakes.Runs);
        Assert.Single(fakes.Fetches);
        fakes.Now += CliStatus.LatestTtl;
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal(2, fakes.Fetches.Count);
        Assert.Equal(3, fakes.Runs.Count);
        await OneAsync(status, StatusFakes.Agents[0], force: true);
        Assert.Equal(4, fakes.Runs.Count);
        Assert.Equal(3, fakes.Fetches.Count);
    }

    [Fact]
    public async Task A_failure_is_retried_sooner_than_a_success()
    {
        var fakes = new StatusFakes { Latest = [] };
        var status = fakes.Status();
        await OneAsync(status, StatusFakes.Agents[0]);
        fakes.Now += CliStatus.FailureTtl - 1;
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Single(fakes.Fetches);
        fakes.Latest = new() { ["@anthropic-ai/claude-code"] = "2.1.280" };
        fakes.Now += 2;
        var row = await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal(2, fakes.Fetches.Count);
        Assert.Equal("2.1.280", row.Latest);
        Assert.True(row.IsOutdated);
    }

    [Fact]
    public async Task Forget_makes_the_next_check_read_the_binary_and_the_source_again()
    {
        var fakes = new StatusFakes();
        var status = fakes.Status();
        await OneAsync(status, StatusFakes.Agents[0]);
        status.Forget("claude");
        await OneAsync(status, StatusFakes.Agents[0]);
        Assert.Equal(2, fakes.Runs.Count);
        Assert.Equal(2, fakes.Fetches.Count);
    }

    [Fact]
    public async Task The_binary_discovery_found_is_the_one_probed_and_is_remembered()
    {
        var paths = new List<string>();
        var fakes = new StatusFakes();
        var status = new CliStatus(fakes.Sources with { RunVersion = (command, path, _) => { paths.Add(path); return fakes.RunAsync(command, path, Ct); } });
        await OneAsync(status, new AgentRef("claude", "Claude Code", "/opt/bin/claude"));
        Assert.Equal("/opt/bin/claude", Assert.Single(paths));
        await status.InstalledAsync("claude", force: true, ct: Ct);
        Assert.Equal("/opt/bin/claude", paths[1]);
    }

    [Fact]
    public async Task A_cancelled_check_is_not_a_row()
    {
        using var cancelled = new CancellationTokenSource();
        await cancelled.CancelAsync();
        var sources = new StatusFakes().Sources with { RunVersion = (_, _, token) => Task.FromCanceled<string>(token) };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new CliStatus(sources).StatusAsync(StatusFakes.Agents, ct: cancelled.Token));
    }

    [Fact]
    public async Task A_homebrew_formula_is_compared_with_what_homebrew_ships_not_npm()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        using var dir = new TempDir();
        var binary = dir.File("Cellar/opencode/1.18.30_2/bin/opencode");
        var link = dir.Link("bin/opencode", binary);
        var shipped = "1.18.30";
        var fetches = new List<string>();
        var fakes = new StatusFakes();
        var sources = fakes.Sources with
        {
            Fetch = (url, _) =>
            {
                fetches.Add(url);
                return Task.FromResult(Encoding.UTF8.GetBytes(url == $"{ReleaseSources.HomebrewFormulaApi}/opencode.json"
                    ? "{\"name\":\"opencode\",\"versions\":{\"stable\":\"" + shipped + "\",\"head\":null}}"
                    : """{"latest":"1.18.32"}"""));
            },
        };
        var status = new CliStatus(sources);
        var agent = new AgentRef("opencode", "Open Router", link);
        var row = await OneAsync(status, agent);
        Assert.Equal(("1.18.30", false, "homebrew"), (row.Latest, row.IsOutdated, row.Source));
        Assert.Equal([$"{ReleaseSources.HomebrewFormulaApi}/opencode.json"], fetches);
        shipped = "1.18.32";
        row = await OneAsync(status, agent, force: true);
        Assert.Equal(("1.18.32", true), (row.Latest, row.IsOutdated));
    }

    [Theory]
    [InlineData("claude-code@latest")]
    [InlineData("claude-code")]
    public async Task A_claude_cask_is_compared_with_anthropics_download_not_npm(string cask)
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        using var dir = new TempDir();
        var link = dir.Link("bin/claude", dir.File($"Caskroom/{cask}/2.1.267/claude"));
        var published = "2.1.267";
        var fetches = new List<string>();
        var sources = new StatusFakes().Sources with
        {
            Fetch = (url, _) =>
            {
                fetches.Add(url);
                return Task.FromResult(Encoding.UTF8.GetBytes(url == ReleaseSources.ClaudeReleaseLatestUrl ? $"{published}\n" : """{"latest":"2.1.292"}"""));
            },
        };
        var status = new CliStatus(sources);
        var agent = new AgentRef("claude", "Claude Code", link);
        var row = await OneAsync(status, agent);
        Assert.Equal(("2.1.267", false, "anthropic"), (row.Latest, row.IsOutdated, row.Source));
        Assert.Equal([ReleaseSources.ClaudeReleaseLatestUrl], fetches);
        published = "2.1.292";
        row = await OneAsync(status, agent, force: true);
        Assert.Equal(("2.1.292", true), (row.Latest, row.IsOutdated));
        Assert.Equal("npm", (await status.LatestAsync("claude", ct: Ct)).Source);
    }

    [Fact]
    public async Task Without_sources_of_its_own_the_foot_reads_the_login_flows_table()
    {
        var fakes = new StatusFakes();
        var status = new CliStatus(fakes.Sources with { CanSignIn = null, NeedsCode = null });

        var rows = (await status.StatusAsync(StatusFakes.Agents, ct: Ct)).Agents.ToDictionary(row => row.Command);

        Assert.True(rows["claude"].CanSignIn);
        Assert.True(rows["claude"].NeedsCode);
        Assert.True(rows["agent"].CanSignIn);
        Assert.False(rows["agent"].NeedsCode);
        Assert.False(rows["agy"].CanSignIn);
    }
}

/// <summary>A scratch folder for symlinked fake installs, deleted with it.</summary>
internal sealed class TempDir : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("clistatus").FullName;

    public string File(string relative)
    {
        var path = Path.Combine(_root, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        System.IO.File.WriteAllText(path, "");
        return path;
    }

    public string Link(string relative, string target)
    {
        var path = Path.Combine(_root, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        System.IO.File.CreateSymbolicLink(path, target);
        return path;
    }

    public void Dispose() => Directory.Delete(_root, recursive: true);
}
