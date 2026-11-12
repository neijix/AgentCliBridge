namespace D3sk.AgentCli.Specs.Grok;

/// <summary>One Grok turn's inputs to <see cref="GrokArgv.Build"/>.</summary>
public sealed record GrokArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt; ignored when it travels on stdin.</summary>
    public string Prompt { get; init; } = "";

    /// <summary>The session id to resume.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }

    /// <summary>The prompt is read from stdin (too long for a command line).</summary>
    public bool PromptOnStdin { get; init; }
}

/// <summary>Headless argv for the Grok CLI.</summary>
public static class GrokArgv
{
    /// <summary>
    /// Grok built-ins that cannot change anything (tool ids from the <c>grok -p</c> init line). MCP
    /// meta-tools are always added, hence <c>--deny MCPTool</c>.
    /// </summary>
    public const string ReadOnlyTools = "read_file,list_dir,grep,todo_write,web_search,web_fetch";

    /// <summary>
    /// The tool-restricting flags for a mode. Grok's own <c>--permission-mode plan</c> still edits, and a
    /// headless Grok cancels its whole turn when a tool needs an approval nobody can give, so plan and
    /// manual keep read-only built-ins, the edit modes deny the shell, MCP tools and subagents, bypass
    /// approves everything, and auto is <c>--always-approve</c>.
    /// </summary>
    public static List<string> PermissionArgs(string? mode)
    {
        var m = Claude.ClaudeArgv.NormalizePermissionMode(mode);
        return m switch
        {
            "plan" or "manual" => ["--tools", ReadOnlyTools, "--disallowed-tools", "Agent", "--deny", "MCPTool"],
            "bypassPermissions" => ["--permission-mode", m],
            "auto" => ["--always-approve"],
            _ => ["--permission-mode", "acceptEdits", "--disallowed-tools", "Agent", "--deny", "Bash", "--deny", "MCPTool"],
        };
    }

    /// <summary>The <c>--model</c> flags; a <c>-high</c> or <c>-low</c> suffix becomes <c>--reasoning-effort</c>. An id starting with '-' throws.</summary>
    public static List<string> ModelArgs(string? model)
    {
        var id = model?.Trim();
        if (string.IsNullOrEmpty(id)) return [];
        if (id.StartsWith('-'))
            throw new ArgumentException($"a model id cannot start with '-': {(id.Length > 40 ? id[..40] : id)}");
        string[] placeholders = ["default", "claude code", "cursor agent", "google antigravity", "gemini cli"];
        if (placeholders.Contains(id.ToLowerInvariant())) return [];
        if (id.EndsWith("-high", StringComparison.Ordinal)) return ["--model", id[..^5], "--reasoning-effort", "high"];
        if (id.EndsWith("-low", StringComparison.Ordinal)) return ["--model", id[..^4], "--reasoning-effort", "low"];
        return ["--model", id];
    }

    /// <summary>The headless argv for one Grok turn; <c>-p -</c> reads the prompt from stdin.</summary>
    public static List<string> Build(GrokArgvRequest r)
    {
        // Without --include-partial-messages Grok prints whole messages only, so no text reaches the host until the turn ends.
        var argv = new List<string>
        {
            r.Binary, "-p", r.PromptOnStdin ? "-" : r.Prompt,
            "--output-format", "streaming-messages-json", "--include-partial-messages",
        };
        argv.AddRange(ModelArgs(r.Model));
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.AddRange(["--resume", r.ResumeId]);
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(r.CliArgs);
        return argv;
    }
}
