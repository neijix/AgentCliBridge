using System.Security.Cryptography;
using System.Text;
using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

public class CliInstallerTests
{
    private const string Url = "https://vendor.example/install.sh";
    private static readonly ScriptSource Source = new(Url, "install.sh", ["/bin/bash"]);

    private static (CliInstaller Installer, FakeHttp Http, FakeRunner Runner) Rig()
    {
        var http = new FakeHttp();
        var runner = new FakeRunner();
        return (new CliInstaller(runner, new ScriptDownloader(http.Client())), http, runner);
    }

    private static CliPlan ScriptPlan(ScriptSource? source = null) => new() { Script = source ?? Source, How = "its install script" };

    [Fact]
    [Trait("Security", "B18")]
    public async Task The_script_is_saved_whole_and_run_from_that_file_never_piped()
    {
        var (installer, http, runner) = Rig();
        http.Bodies[Url] = Encoding.UTF8.GetBytes("echo installed");
        var outcome = await installer.RunAsync(ScriptPlan(), TestContext.Current.CancellationToken);
        Assert.True(outcome.Ok);
        var argv = Assert.Single(runner.Ran);
        Assert.Equal("/bin/bash", argv[0]);
        Assert.Equal(2, argv.Length);  // no -c, no pipe: the interpreter and one file
        Assert.EndsWith("install.sh", argv[1]);
        Assert.Equal("echo installed", runner.FileSeen[0]);  // the whole file was on disk when it ran
        Assert.False(File.Exists(argv[1]));  // and the saved copy is cleaned up
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_script_whose_hash_differs_from_the_vendors_published_one_is_never_run()
    {
        var (installer, http, runner) = Rig();
        http.Bodies[Url] = Encoding.UTF8.GetBytes("echo tampered");
        http.Bodies[Url + ".sha256"] = Encoding.ASCII.GetBytes(new string('a', 64) + "  install.sh\n");
        var outcome = await installer.RunAsync(ScriptPlan(Source with { ChecksumUrl = Url + ".sha256" }), TestContext.Current.CancellationToken);
        Assert.False(outcome.Ok);
        Assert.Equal("checksum", outcome.Step);
        Assert.Contains("nothing was run", outcome.Message);
        Assert.Empty(runner.Ran);
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_script_that_matches_the_published_checksum_runs()
    {
        var (installer, http, runner) = Rig();
        var body = Encoding.UTF8.GetBytes("echo fine");
        http.Bodies[Url] = body;
        http.Bodies[Url + ".sha256"] = Encoding.ASCII.GetBytes($"other-file {new string('0', 64)}\n{Convert.ToHexStringLower(SHA256.HashData(body))}  install.sh\n");
        var outcome = await installer.RunAsync(ScriptPlan(Source with { ChecksumUrl = Url + ".sha256" }), TestContext.Current.CancellationToken);
        Assert.True(outcome.Ok);
        Assert.Single(runner.Ran);
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_checksum_file_with_no_hash_stops_the_install()
    {
        var (installer, http, runner) = Rig();
        http.Bodies[Url] = "x"u8.ToArray();
        http.Bodies[Url + ".sha256"] = "<html>not found</html>"u8.ToArray();
        var outcome = await installer.RunAsync(ScriptPlan(Source with { ChecksumUrl = Url + ".sha256" }), TestContext.Current.CancellationToken);
        Assert.Equal("checksum", outcome.Step);
        Assert.Empty(runner.Ran);
    }

    [Theory]
    [Trait("Security", "B18")]
    [InlineData("http://vendor.example/install.sh")]
    [InlineData("file:///etc/passwd")]
    [InlineData("ftp://vendor.example/install.sh")]
    public async Task A_download_that_is_not_https_is_refused_before_any_request(string url)
    {
        var (installer, http, runner) = Rig();
        var outcome = await installer.RunAsync(ScriptPlan(Source with { Url = url }), TestContext.Current.CancellationToken);
        Assert.Equal("download", outcome.Step);
        Assert.Empty(http.Requests);
        Assert.Empty(runner.Ran);
    }

    [Fact]
    [Trait("Security", "B18")]
    public async Task A_script_past_the_size_cap_is_not_run()
    {
        var (installer, http, runner) = Rig();
        http.Bodies[Url] = new byte[ScriptDownloader.MaxScriptBytes + 1];
        var outcome = await installer.RunAsync(ScriptPlan(), TestContext.Current.CancellationToken);
        Assert.Equal("download", outcome.Step);
        Assert.Empty(runner.Ran);
    }

    [Fact]
    public async Task A_failed_download_says_the_step_and_the_reason()
    {
        var (installer, _, runner) = Rig();  // the fake answers 404
        var outcome = await installer.RunAsync(ScriptPlan(), TestContext.Current.CancellationToken);
        Assert.False(outcome.Ok);
        Assert.Equal("download", outcome.Step);
        Assert.Contains("vendor.example", outcome.Message);
        Assert.Contains("404", outcome.Message);
        Assert.Empty(runner.Ran);
    }

    [Fact]
    public async Task Steps_run_in_order_and_the_first_failure_stops_the_rest_and_names_itself()
    {
        var (installer, _, runner) = Rig();
        runner.Answer = argv => argv[1] == "fetch" ? new ProcessResult(1, "Could not resolve host") : new ProcessResult(0, "ok");
        var plan = UpdatePlans.Update("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code/2.1.267/claude");
        var outcome = await installer.RunAsync(plan, TestContext.Current.CancellationToken);
        Assert.False(outcome.Ok);
        Assert.Equal("run", outcome.Step);
        Assert.Contains("brew failed (step 1 of 3)", outcome.Message);
        Assert.Contains("Could not resolve host", outcome.Output);
        Assert.Equal(["fetch"], runner.Ran.Select(a => a[1]));  // no uninstall, no install

        runner.Answer = _ => new ProcessResult(0, "ok");
        runner.Ran.Clear();
        Assert.True((await installer.RunAsync(plan, TestContext.Current.CancellationToken)).Ok);
        Assert.Equal(["fetch", "uninstall", "install"], runner.Ran.Select(a => a[1]));
    }

    [Fact]
    public async Task A_program_that_cannot_start_is_reported_with_its_reason()
    {
        var (installer, _, runner) = Rig();
        runner.Answer = argv => new ProcessResult(-1, $"Could not start {argv[0]}: Access is denied");
        var outcome = await installer.RunAsync(new CliPlan { Argv = ["/opt/x/npm", "install", "-g", "p"] }, TestContext.Current.CancellationToken);
        Assert.Equal("run", outcome.Step);
        Assert.Contains("Access is denied", outcome.Message);
    }

    [Fact]
    public async Task A_plan_the_host_cannot_carry_out_fails_at_the_plan_step_with_its_hint()
    {
        var (installer, _, runner) = Rig();
        var outcome = await installer.RunAsync(new CliPlan { Hint = "install Node.js first" }, TestContext.Current.CancellationToken);
        Assert.Equal("plan", outcome.Step);
        Assert.Contains("install Node.js first", outcome.Message);
        Assert.Empty(runner.Ran);
    }

    [Fact]
    public async Task A_native_uninstall_removes_the_files_without_starting_anything()
    {
        var (installer, _, runner) = Rig();
        var dir = Directory.CreateTempSubdirectory("native").FullName;
        try
        {
            File.WriteAllText(Path.Combine(dir, "f"), "x");
            var outcome = await installer.RunAsync(new CliPlan { Remove = new RemoveTarget(dir, []) }, TestContext.Current.CancellationToken);
            Assert.True(outcome.Ok);
            Assert.False(Directory.Exists(dir));
            Assert.Empty(runner.Ran);
        }
        finally
        {
            if (Directory.Exists(dir))
            {
                Directory.Delete(dir, true);
            }
        }
    }

    [Fact]
    public void The_expected_hash_reads_bare_and_listed_forms()
    {
        Assert.Null(ScriptDownloader.ExpectedHash("abc  install.sh", "install.sh"));
        var hash = new string('B', 64);
        Assert.Equal(new string('b', 64), ScriptDownloader.ExpectedHash(hash + "\n", "install.sh"));
        Assert.Equal(new string('c', 64), ScriptDownloader.ExpectedHash($"{hash}  other\n{new string('c', 64)} *install.sh", "install.sh"));
    }
}
