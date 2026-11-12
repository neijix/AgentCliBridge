using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Local;

namespace D3sk.AgentCli.Tests.Local;

[System.Runtime.Versioning.UnsupportedOSPlatform("windows")]
public class MlxChatTests
{
    private const string Model = "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit";
    private const string Key = "fake-key-for-tests-only";
    private const string Sse =
        "data: {\"choices\":[{\"delta\":{\"content\":\"Hi\"}}]}\n\n"
        + "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"…\",\"content\":\" there\"}}]}\n\n"
        + "data: [DONE]\n";

    private static FakeReply Keyed(SeenRequest r, FakeReply chat) =>
        r.Authorization is null || r.Authorization != $"Bearer {Key}"
            ? new FakeReply(401, "{\"detail\":\"key required\"}")
            : r.Path == "/v1/models" ? new FakeReply(200, "{\"data\":[]}") : chat;

    private static FakeReply Stream(string body) => new(200, body, "text/event-stream");

    private static MlxOptions Options(FakeMlxServer server, string? key = Key) => new()
    {
        KeySource = () => key,
        SocketPath = server.SocketPath,
        LegacyPortToProbe = 1,
        ReplyRules = ["Say done."],
        ProbeTimeout = TimeSpan.FromSeconds(5),
    };

    private static async Task<List<StreamEvent>> RunAsync(MlxOptions options, string model = Model, string prompt = "hello", IReadOnlyList<string>? installed = null)
    {
        var events = new List<StreamEvent>();
        await foreach (var e in MlxChat.StreamTurnAsync(model, prompt, "/work/proj", null, options, installed ?? [Model], TestContext.Current.CancellationToken))
        {
            events.Add(e);
        }

        return events;
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_turn_streams_text_and_thinking_and_completes()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(Sse)));
        var events = await RunAsync(Options(server));

        Assert.Equal(
            [new TextDelta("Hi"), new ThinkingDelta("…"), new TextDelta(" there"), new Completed(0)],
            events.ToArray());
        var chat = server.Requests.Single(r => r.Path == "/v1/chat/completions");
        Assert.Equal($"Bearer {Key}", chat.Authorization);
        var body = JsonNode.Parse(chat.Body)!;
        Assert.Equal(Model, (string?)body["model"]);
        Assert.True((bool)body["stream"]!);
        Assert.Equal(8192, (int)body["max_tokens"]!);
        var system = (string)body["messages"]![0]!["content"]!;
        Assert.Contains("You have no tools", system);
        Assert.Contains("project 'proj' at /work/proj", system);
        Assert.EndsWith("Say done.", system);
        Assert.Equal("hello", (string?)body["messages"]![1]!["content"]);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_model_that_is_not_downloaded_never_calls_out()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(Sse)));
        var events = await RunAsync(Options(server), "mlx-community/nope");

        Assert.Empty(server.Requests);
        Assert.Equal("mlx_failed", Assert.IsType<StreamError>(events[0]).Code);
        Assert.Equal(new Completed(1), events[^1]);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task An_empty_model_takes_the_first_downloaded_one()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(Sse)));
        await RunAsync(Options(server), "");

        var body = JsonNode.Parse(server.Requests.Single(r => r.Path == "/v1/chat/completions").Body)!;
        Assert.Equal(Model, (string?)body["model"]);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_json_answer_instead_of_a_stream_is_one_text_reply()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, new FakeReply(200, "{\"choices\":[{\"message\":{\"content\":\"whole\"}}]}")));
        Assert.Equal([new TextDelta("whole"), new Completed(0)], (await RunAsync(Options(server))).ToArray());
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task An_http_error_shows_its_detail_and_an_error_object_in_the_stream_fails_the_turn()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var failing = new FakeMlxServer(r => Keyed(r, new FakeReply(500, "{\"error\":{\"message\":\"out of memory\"}}")));
        var events = await RunAsync(Options(failing));
        Assert.Equal(new StreamError("out of memory", "mlx_failed"), events[0]);
        Assert.Equal(new Completed(1), events[1]);

        using var inStream = new FakeMlxServer(r => Keyed(r, Stream("data: {\"error\":{\"message\":\"model crashed\"}}\n\n")));
        var second = await RunAsync(Options(inStream));
        Assert.Equal(new StreamError("model crashed", "mlx_failed"), second[0]);
        Assert.Equal(new Completed(1), second[1]);
    }

    [Fact]
    [Trait("Category", "Preserve")]
    public async Task A_reply_with_no_text_is_an_error()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(": comment\n\ndata: [DONE]\n")));
        var events = await RunAsync(Options(server));
        Assert.Equal(new StreamError("The local model returned nothing.", "mlx_failed"), events[0]);
        Assert.Equal(new Completed(1), events[1]);
    }

    [Fact]
    public async Task A_slow_server_shows_one_loading_notice_before_the_reply()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, r.Path == "/v1/chat/completions" ? new FakeReply(200, Sse, "text/event-stream", HeadDelay: TimeSpan.FromMilliseconds(600)) : Stream(Sse)));
        var events = await RunAsync(Options(server) with { LoadNoticeDelay = TimeSpan.FromMilliseconds(100) });

        Assert.Equal(new Notice("Loading Qwen2.5-Coder-32B-Instruct-4bit…", "loading"), events[0]);
        Assert.Single(events, e => e is Notice);
        Assert.Equal(new Completed(0), events[^1]);
    }

    [Fact]
    public async Task A_quick_server_shows_no_notice()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(Sse)));
        var events = await RunAsync(Options(server) with { LoadNoticeDelay = TimeSpan.FromSeconds(30) });

        Assert.DoesNotContain(events, e => e is Notice);
    }

    [Fact]
    public async Task Cancelling_closes_the_stream_without_an_error_or_a_completion()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, new FakeReply(200, "data: {\"choices\":[{\"delta\":{\"content\":\"Hi\"}}]}\n\n", "text/event-stream", StallAfterBody: true)));
        using var cancel = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);
        var events = new List<StreamEvent>();
        await foreach (var e in MlxChat.StreamTurnAsync(Model, "hello", "/work/proj", "proj", Options(server), [Model], cancel.Token))
        {
            events.Add(e);
            cancel.Cancel();
        }

        Assert.Equal([new TextDelta("Hi")], events.ToArray());
    }

    [Fact]
    public async Task A_wrong_key_is_named_and_the_key_is_never_printed()
    {
        Assert.SkipWhen(OperatingSystem.IsWindows(), "Unix socket transport");
        using var server = new FakeMlxServer(r => Keyed(r, Stream(Sse)));
        var events = await RunAsync(Options(server, "some-other-key"));
        var error = Assert.IsType<StreamError>(events[0]);
        Assert.Contains("refused the key", error.Message);
        Assert.DoesNotContain("some-other-key", error.Message);
    }

    [Fact]
    public void Only_a_finished_mlx_community_snapshot_is_offered()
    {
        var cache = Directory.CreateTempSubdirectory("mlx-cache-").FullName;
        try
        {
            Snapshot(cache, Model, ready: true);
            Snapshot(cache, "mlx-community/gemma-3-27b-it-4bit", ready: false);
            Directory.CreateDirectory(Path.Combine(cache, "models--meta-llama--Llama-3.1-8B"));
            Assert.Equal([Model], MlxModels.Installed(cache));
            Assert.Empty(MlxModels.Installed(Path.Combine(cache, "missing")));
            Assert.Equal("Qwen2.5-Coder-32B-Instruct-4bit", MlxModels.Short(Model));
        }
        finally
        {
            Directory.Delete(cache, recursive: true);
        }
    }

    private static void Snapshot(string root, string id, bool ready)
    {
        var snap = Path.Combine(root, "models--" + id.Replace("/", "--", StringComparison.Ordinal), "snapshots", "abc");
        Directory.CreateDirectory(snap);
        if (ready)
        {
            File.WriteAllText(Path.Combine(snap, "config.json"), "{}");
        }
    }
}
