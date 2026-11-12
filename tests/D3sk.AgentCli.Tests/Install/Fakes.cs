using System.Net;
using D3sk.AgentCli.Install;

namespace D3sk.AgentCli.Tests.Install;

/// <summary>An HTTP client that answers from a table and never touches the network.</summary>
internal sealed class FakeHttp : HttpMessageHandler
{
    public Dictionary<string, byte[]> Bodies { get; } = [];

    public List<string> Requests { get; } = [];

    public HttpClient Client() => new(this);

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var url = request.RequestUri!.ToString();
        Requests.Add(url);
        if (!Bodies.TryGetValue(url, out var body))
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound) { RequestMessage = request });
        }
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(body), RequestMessage = request });
    }
}

/// <summary>A process runner that records every argv and answers from a script; never starts anything.</summary>
internal sealed class FakeRunner : IProcessRunner
{
    public List<string[]> Ran { get; } = [];

    /// <summary>What was on disk at each program when it "ran" (read at call time).</summary>
    public List<string?> FileSeen { get; } = [];

    public Func<string[], ProcessResult> Answer { get; set; } = _ => new ProcessResult(0, "ok");

    public Task<ProcessResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct)
    {
        Ran.Add([.. argv]);
        FileSeen.Add(File.Exists(argv[^1]) ? File.ReadAllText(argv[^1]) : null);
        return Task.FromResult(Answer([.. argv]));
    }
}
