using System.Text;
using System.Text.Json;
using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Tests.Status;

/// <summary>A fake <c>--version</c> runner and release-source fetcher that count their calls; no process, no network.</summary>
internal sealed class StatusFakes
{
    public static readonly byte[] CursorScript = Encoding.UTF8.GetBytes(
        "#!/bin/bash\nDOWNLOAD_URL=\"https://downloads.cursor.com/lab/2026.09.18-9a7762b/${OS}/${ARCH}/agent-cli-package.tar.gz\"\n");

    public static readonly Dictionary<string, string> VersionOutput = new()
    {
        ["claude"] = "2.1.267 (Claude Code)\n",
        ["gemini"] = "0.60.0\n",
        ["agent"] = "2026.09.18-9a7762b\n",
        ["agy"] = "1.2.8\n",
        ["copilot"] = "GitHub Copilot CLI 1.0.87.\n",
        ["grok"] = "grok 1.0.40 (eb1a2256660d) [alpha]\n",
        ["opencode"] = "1.18.30\n",
    };

    public static readonly AgentRef[] Agents =
    [
        new("claude", "Claude Code"),
        new("agent", "Cursor Agent"),
        new("agy", "Google Antigravity"),
        new("grok", "Grok CLI"),
        new("opencode", "Open Router"),
    ];

    public Dictionary<string, string> Latest { get; set; } = new()
    {
        ["@anthropic-ai/claude-code"] = "2.1.280",
        ["opencode-ai"] = "1.18.32",
        ["@xai-official/grok"] = "1.0.40",
    };

    public HashSet<string> Broken { get; } = [];
    public List<string> Runs { get; } = [];
    public List<string> Fetches { get; } = [];
    public double Now { get; set; } = 1_000.0;

    public CliStatusSources Sources => new()
    {
        RunVersion = RunAsync,
        Fetch = FetchAsync,
        Clock = () => Now,
        CanSignIn = command => command is "claude" or "agent" or "grok" or "opencode" or "copilot",
        NeedsCode = command => command is "claude" or "opencode",
    };

    public CliStatus Status() => new(Sources);

    public Task<string> RunAsync(string command, string path, CancellationToken ct)
    {
        Runs.Add(command);
        return Broken.Contains(command)
            ? throw new FileNotFoundException($"{command}: not found")
            : Task.FromResult(VersionOutput[command]);
    }

    public Task<byte[]> FetchAsync(string url, CancellationToken ct)
    {
        Fetches.Add(url);
        if (url == ReleaseSources.CursorInstallUrl)
        {
            return Task.FromResult(CursorScript);
        }
        foreach (var (package, version) in Latest)
        {
            if (url.Contains(package.Replace("/", "%2F", StringComparison.Ordinal), StringComparison.Ordinal))
            {
                return Task.FromResult(JsonSerializer.SerializeToUtf8Bytes(new Dictionary<string, string> { ["stable"] = "0.0.1", ["latest"] = version }));
            }
        }
        throw new IOException("registry down");
    }
}
