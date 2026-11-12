using System.Threading.Channels;
using D3sk.AgentCli.Login;

namespace D3sk.AgentCli.Tests.Login;

/// <summary>A stand-in for the CLIs: nothing real is started. Scripts say what each command prints.</summary>
internal sealed class FakeLoginHost : ILoginHost
{
    public Dictionary<string, string> Env { get; } = [];

    public List<string> Events { get; } = [];

    public List<FakeProcess> Started { get; } = [];

    /// <summary>Lines each sign-in prints right after it starts.</summary>
    public string[] LoginLines { get; set; } = [];

    /// <summary>Answers a status or logout command by its argv.</summary>
    public Func<IReadOnlyList<string>, LoginCommandResult> Answer { get; set; } = _ => new LoginCommandResult(0, "", "");

    public bool Stubborn { get; set; }

    public IReadOnlyDictionary<string, string> Environment => Env;


    public Dictionary<string, string> LastEnv { get; } = [];

    public ILoginProcess Start(IReadOnlyList<string> argv, IReadOnlyDictionary<string, string> envOverlay, bool keepStdin)
    {
        Events.Add("start");
        LastEnv.Clear();
        foreach (var (k, v) in envOverlay)
        {
            LastEnv[k] = v;
        }
        var process = new FakeProcess(argv, keepStdin, Stubborn);
        foreach (var line in LoginLines)
        {
            process.Print(line);
        }
        Started.Add(process);
        return process;
    }

    public Task<LoginCommandResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct)
        => Task.FromResult(Answer(argv));

    public void ClearQuarantine(string binary) => Events.Add($"clear:{binary}");
}

internal sealed class FakeProcess(IReadOnlyList<string> argv, bool keepStdin, bool stubborn) : ILoginProcess
{
    private readonly Channel<string> _lines = Channel.CreateUnbounded<string>();

    public IReadOnlyList<string> Argv { get; } = argv;

    public List<string> Calls { get; } = [];

    public List<string> Written { get; } = [];

    public bool HasExited { get; private set; }

    public int? ExitCode { get; private set; }

    public bool CanWrite { get; } = keepStdin;

    public void Print(string line) => _lines.Writer.TryWrite(line + "\n");

    public void Exit(int code)
    {
        HasExited = true;
        ExitCode = code;
        _lines.Writer.TryComplete();
    }

    public IAsyncEnumerable<string> ReadLinesAsync(CancellationToken ct) => _lines.Reader.ReadAllAsync(ct);

    public ValueTask WriteAsync(string text, CancellationToken ct)
    {
        if (HasExited)
        {
            throw new IOException("gone");
        }
        Written.Add(text);
        return ValueTask.CompletedTask;
    }

    public void Terminate()
    {
        Calls.Add("terminate");
        if (!stubborn)
        {
            Exit(-15);
        }
    }

    public void Kill()
    {
        Calls.Add("kill");
        Exit(-9);
    }

    public Task<bool> WaitForExitAsync(TimeSpan timeout, CancellationToken ct)
    {
        Calls.Add("wait");
        return Task.FromResult(HasExited);
    }
}
