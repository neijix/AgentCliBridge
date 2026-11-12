using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Security;

/// <summary>
/// A durable record of every security stop a turn hit: one JSON line per stop, with the page it is about and
/// an id the app turns into a details link. Writing is best effort: a log that cannot be written never breaks
/// a turn. Command text is stored with token values redacted. The file is private to the user, a symlink is
/// never written through, and it rolls over to <c>.1</c> past <see cref="MaxBytes"/>.
/// </summary>
public sealed class SecurityLog
{
    /// <summary>Environment variable that moves the log, or turns it off with <c>off</c>.</summary>
    public const string EnvVar = "AGENT_CLI_BRIDGE_SECURITY_LOG";

    /// <summary>Environment variable naming the gateway the details link points at.</summary>
    public const string GatewayUrlVar = "AGENT_CLI_BRIDGE_URL";

    /// <summary>The gateway address when <see cref="GatewayUrlVar"/> is not set.</summary>
    public const string DefaultGatewayUrl = "http://127.0.0.1:4747";

    /// <summary>Size past which the live file rolls over.</summary>
    public const int MaxBytes = 2_000_000;

    /// <summary>Entry kind: the guard flagged a tool's output.</summary>
    public const string InjectionDetectedKind = "injection_detected";

    /// <summary>Entry kind: the guard denied a tool approval on a tainted turn.</summary>
    public const string ActionBlockedKind = "action_blocked";

    /// <summary>Entry kind: the scout withheld a page it rated high risk.</summary>
    public const string PageWithheldKind = "page_withheld";

    private static readonly string[] DisabledValues = ["off", "none", "0", "false"];
    private static readonly Lock WriteLock = new();

    /// <summary>The JSON-lines file; null writes nothing.</summary>
    public string? Path { get; }

    /// <summary>Which host ran the turn, so the log tells them apart.</summary>
    public string Source { get; }

    /// <summary>A log at <paramref name="path"/>, or at <see cref="DefaultPath"/> when null and not turned off.</summary>
    public SecurityLog(string? path = null, string source = "agent-cli-bridge")
    {
        Path = path ?? DefaultPath();
        Source = source;
    }

    /// <summary>
    /// The environment variable's path when set (null when it says off), else the home file. With an
    /// <paramref name="env"/> mapping it only names the path; the process environment also creates the home folder.
    /// </summary>
    public static string? DefaultPath(IReadOnlyDictionary<string, string>? env = null)
    {
        string Get(string key) => (env is null ? Environment.GetEnvironmentVariable(key) : env.GetValueOrDefault(key))?.Trim() ?? "";
        var explicitPath = Get(EnvVar);
        if (DisabledValues.Contains(explicitPath, StringComparer.OrdinalIgnoreCase))
        {
            return null;
        }
        if (explicitPath.Length > 0)
        {
            return ExpandUser(explicitPath);
        }
        string home;
        if (env is null)
        {
            home = ClaudeArgv.BridgeHomePath();
            Directory.CreateDirectory(home);
            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(home, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            }
        }
        else
        {
            var configured = Get("AGENT_CLI_BRIDGE_HOME");
            home = configured.Length > 0 ? ExpandUser(configured) : System.IO.Path.Combine(ExpandUser("~"), ".agent-cli-bridge");
        }
        return System.IO.Path.Combine(home, "security-log.jsonl");
    }

    /// <summary>The gateway page showing one entry (<see cref="GatewayUrlVar"/> when the gateway moved).</summary>
    public static string EntryUrl(string entryId, IReadOnlyDictionary<string, string>? env = null)
    {
        var configured = (env is null ? Environment.GetEnvironmentVariable(GatewayUrlVar) : env.GetValueOrDefault(GatewayUrlVar))?.Trim() ?? "";
        return $"{(configured.Length > 0 ? configured : DefaultGatewayUrl).TrimEnd('/')}/security#e-{entryId}";
    }

    /// <summary>Appends one entry; its id, or "" when nothing was written.</summary>
    public string Record(JsonObject entry)
    {
        if (Path is null)
        {
            return "";
        }
        var entryId = Guid.NewGuid().ToString("N")[..12];
        var line = new JsonObject
        {
            ["id"] = entryId,
            ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
            ["source"] = Source,
        };
        foreach (var (key, value) in (JsonObject)SecurityText.RedactNode(entry)!)
        {
            line[key] = value?.DeepClone();
        }
        try
        {
            lock (WriteLock)
            {
                Append(line.ToJsonString(SecurityText.Json) + "\n");
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return "";
        }
        return entryId;
    }

    /// <summary>The latest entries, newest first (the rolled-over file included).</summary>
    public List<JsonObject> Entries(int limit = 500)
    {
        var result = new List<JsonObject>();
        if (Path is null)
        {
            return result;
        }
        var lines = new List<string>();
        foreach (var file in new[] { Path + ".1", Path })
        {
            try
            {
                lines.AddRange(File.ReadAllText(file).Split('\n', StringSplitOptions.RemoveEmptyEntries));
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
            }
        }
        for (var i = lines.Count - 1; i >= 0 && result.Count < limit; i--)
        {
            try
            {
                if (JsonNode.Parse(lines[i]) is JsonObject entry)
                {
                    result.Add(entry);
                }
            }
            catch (JsonException)
            {
            }
        }
        return result;
    }

    /// <summary>Deletes the log and its rolled-over file.</summary>
    public void Clear()
    {
        if (Path is null)
        {
            return;
        }
        lock (WriteLock)
        {
            File.Delete(Path);
            File.Delete(Path + ".1");
        }
    }

    /// <summary>One turn's view of the log.</summary>
    public TurnRecorder Turn(string command, string? model, string? cwd) => new(this, command, model ?? "", cwd ?? "");

    private void Append(string text)
    {
        var path = Path!;
        RefuseSymlink(path);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path))!);
        if (File.Exists(path) && new FileInfo(path).Length > MaxBytes)
        {
            File.Move(path, path + ".1", true);
        }
        var options = new FileStreamOptions { Mode = FileMode.Append, Access = FileAccess.Write, Share = FileShare.ReadWrite };
        if (!OperatingSystem.IsWindows())
        {
            options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        }
        using (var stream = new FileStream(path, options))
        {
            stream.Write(System.Text.Encoding.UTF8.GetBytes(text));
        }
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
    }

    private static void RefuseSymlink(string path)
    {
        if (new FileInfo(path).LinkTarget is not null)
        {
            throw new IOException($"refusing to follow the symlink {path}");
        }
    }

    private static string ExpandUser(string path)
    {
        if (path != "~" && !path.StartsWith("~/", StringComparison.Ordinal) && !path.StartsWith("~\\", StringComparison.Ordinal))
        {
            return path;
        }
        return System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), path.Length > 2 ? path[2..] : "");
    }
}
