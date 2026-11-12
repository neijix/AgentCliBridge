namespace D3sk.AgentCli.Local;

/// <summary>Where D3SKMODEL is and how to reach it. The key is read from the OS keychain by the host; this library never stores or logs it.</summary>
public sealed record MlxOptions
{
    /// <summary>The keychain entry D3SKMODEL's setup creates (service name).</summary>
    public const string KeychainEntry = "d3sk/d3skmodel";

    /// <summary>The keychain account of <see cref="KeychainEntry"/>.</summary>
    public const string KeychainAccount = "d3skmodel";

    /// <summary>The display name used in every message and state.</summary>
    public const string Name = "MLX";

    /// <summary>D3SKMODEL's old plain OpenAI port. It is only probed for a listener (a TCP connect, no bytes), never spoken to.</summary>
    public const int LegacyPort = 8899;

    /// <summary>Returns the bearer key from the keychain (entry <see cref="KeychainEntry"/>), or null when there is none.</summary>
    public required Func<string?> KeySource { get; init; }

    /// <summary>D3SKMODEL's user-only Unix socket; default <c>~/.d3skmodel/api.sock</c>. Ignored when <see cref="HttpsBase"/> is set.</summary>
    public string SocketPath { get; init; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".d3skmodel", "api.sock");

    /// <summary>A TLS endpoint instead of the socket. Anything but <c>https</c> is refused.</summary>
    public Uri? HttpsBase { get; init; }

    /// <summary>The port probed for a server that has not been upgraded.</summary>
    public int LegacyPortToProbe { get; init; } = LegacyPort;

    /// <summary>The HuggingFace hub cache listing the downloaded weights; default <c>~/.cache/huggingface/hub</c>.</summary>
    public string? ModelCache { get; init; }

    /// <summary>The closing rules the host appends to the system text (the hub's reply rules).</summary>
    public IReadOnlyList<string> ReplyRules { get; init; } = [];

    /// <summary>How long a probe may take.</summary>
    public TimeSpan ProbeTimeout { get; init; } = TimeSpan.FromSeconds(5);

    /// <summary>How long the server may take to start answering a chat before the turn shows a "Loading the model" <see cref="D3sk.AgentCli.Events.Notice"/>; it is the server that loads the model, on the first request.</summary>
    public TimeSpan LoadNoticeDelay { get; init; } = TimeSpan.FromSeconds(2);

    /// <summary>How long the stream may stay silent; a chat itself can run for minutes.</summary>
    public TimeSpan StreamIdleTimeout { get; init; } = TimeSpan.FromSeconds(600);
}
