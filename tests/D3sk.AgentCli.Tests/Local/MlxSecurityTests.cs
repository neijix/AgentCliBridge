using D3sk.AgentCli.Events;
using D3sk.AgentCli.Local;

namespace D3sk.AgentCli.Tests.Local;

/// <summary>Row 47, Δ B17: the key comes from the keychain, plain HTTP is refused, a server that is not upgraded is a named state.</summary>
[Trait("Category", "Security")]
[System.Runtime.Versioning.UnsupportedOSPlatform("windows")]
public class MlxSecurityTests
{
    private const string Model = "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit";
    private const string Key = "fake-key-for-tests-only";

    private static MlxOptions Options(string socket, Uri? https = null, int legacyPort = 1, string? key = Key) => new()
    {
        KeySource = () => key,
        SocketPath = socket,
        HttpsBase = https,
        LegacyPortToProbe = legacyPort,
        ProbeTimeout = TimeSpan.FromSeconds(5),
    };

    private static async Task<List<StreamEvent>> RunAsync(MlxOptions options)
    {
        var events = new List<StreamEvent>();
        await foreach (var e in MlxChat.StreamTurnAsync(Model, "hello", "/work/proj", null, options, [Model], TestContext.Current.CancellationToken))
        {
            events.Add(e);
        }

        return events;
    }

    private static void AssertNeedsUpdate(List<StreamEvent> events)
    {
        var error = Assert.IsType<StreamError>(events[0]);
        Assert.Equal(LocalServiceState.NeedsUpdateCode, error.Code);
        Assert.Contains("MLX needs an update", error.Message);
        Assert.Equal(new Completed(1), events[1]);
    }

    [Fact]
    public async Task A_plain_http_endpoint_is_refused_and_nothing_is_sent_to_it()
    {
        using var plain = new FakePlainServer();
        var options = Options("/nonexistent/api.sock", new Uri($"http://127.0.0.1:{plain.Port}/"));

        AssertNeedsUpdate(await RunAsync(options));
        await Task.Delay(200, TestContext.Current.CancellationToken);
        Assert.Equal(0, plain.Connections);
        Assert.Equal(0, plain.BytesReceived);
    }

    [Fact]
    public async Task A_server_with_only_its_old_plain_port_is_a_service_needs_update_and_is_never_spoken_to()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var plain = new FakePlainServer();
        var missing = Path.Combine(Path.GetTempPath(), "mlx-no-such-folder", "api.sock");
        var options = Options(missing, legacyPort: plain.Port);

        AssertNeedsUpdate(await RunAsync(options));
        using var link = await MlxLink.ConnectAsync(options, TestContext.Current.CancellationToken);
        Assert.Equal(LocalServiceStatus.NeedsUpdate, link.State.Status);
        Assert.Contains("MLX", link.State.Service);
        await Task.Delay(200, TestContext.Current.CancellationToken);
        Assert.Equal(0, plain.BytesReceived);
    }

    [Fact]
    public async Task Nothing_listening_is_not_running_not_an_update()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        var missing = Path.Combine(Path.GetTempPath(), "mlx-no-such-folder", "api.sock");
        using var link = await MlxLink.ConnectAsync(Options(missing, legacyPort: 1), TestContext.Current.CancellationToken);
        Assert.Equal(LocalServiceStatus.NotRunning, link.State.Status);
    }

    [Fact]
    public async Task A_server_that_checks_no_key_never_receives_the_key()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(_ => new FakeReply(200, "{\"data\":[]}"));

        AssertNeedsUpdate(await RunAsync(Options(server.SocketPath)));
        Assert.NotEmpty(server.Requests);
        Assert.All(server.Requests, r => Assert.Null(r.Authorization));
        Assert.DoesNotContain(server.Requests, r => r.Path == "/v1/chat/completions");
    }

    [Fact]
    public async Task A_socket_folder_open_to_other_users_gets_no_key_and_no_request()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(_ => new FakeReply(401, "{}"), UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute);

        AssertNeedsUpdate(await RunAsync(Options(server.SocketPath)));
        Assert.Empty(server.Requests);
    }

    [Fact]
    public async Task Without_a_key_in_the_keychain_nothing_is_sent_anywhere()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(_ => new FakeReply(401, "{}"));

        var events = await RunAsync(Options(server.SocketPath, key: null));
        Assert.Equal(LocalServiceState.NoKeyCode, Assert.IsType<StreamError>(events[0]).Code);
        Assert.Contains("d3sk/d3skmodel", ((StreamError)events[0]).Message);
        Assert.Empty(server.Requests);

        using var blank = await MlxLink.ConnectAsync(Options(server.SocketPath, key: "  "), TestContext.Current.CancellationToken);
        Assert.Equal(LocalServiceStatus.NoKey, blank.State.Status);
    }

    [Fact]
    public async Task A_keyed_user_only_socket_is_ready_and_the_key_is_sent_only_after_an_unkeyed_request_was_refused()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => r.Authorization == $"Bearer {Key}" ? new FakeReply(200, "{}") : new FakeReply(401, "{}"));

        using var link = await MlxLink.ConnectAsync(Options(server.SocketPath), TestContext.Current.CancellationToken);
        Assert.True(link.State.IsReady);
        var first = server.Requests.First();
        Assert.Null(first.Authorization);
    }

    [Fact]
    public void The_keychain_entry_is_the_one_d3skmodel_setup_creates()
    {
        Assert.Equal("d3sk/d3skmodel", MlxOptions.KeychainEntry);
        Assert.Equal("d3skmodel", MlxOptions.KeychainAccount);
    }
}
