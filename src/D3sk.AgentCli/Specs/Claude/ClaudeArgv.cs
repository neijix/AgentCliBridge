using D3sk.AgentCli.Catalog;
namespace D3sk.AgentCli.Specs.Claude;

/// <summary>One Claude turn's inputs to <see cref="ClaudeArgv.Build"/>.</summary>
public sealed record ClaudeArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt; ignored when it travels on stdin.</summary>
    public string Prompt { get; init; } = "";

    /// <summary>Appended to the CLI's system prompt.</summary>
    public string SystemText { get; init; } = "";

    /// <summary>The session id to resume.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }

    /// <summary>Prompt and approvals travel as stream-json on stdin.</summary>
    public bool LiveInput { get; init; }

    /// <summary>The prompt is read from stdin (too long for a command line).</summary>
    public bool PromptOnStdin { get; init; }

    /// <summary>Replaces the default <c>--allowedTools</c> list; empty adds none.</summary>
    public IReadOnlyList<string>? AllowedTools { get; init; }

    /// <summary>Settings › Sudo. Off (the default) disallows sudo, pkexec and doas.</summary>
    public bool AllowSudo { get; init; }

    /// <summary>Composer effort level; unknown or "auto" adds no flag.</summary>
    public string? Effort { get; init; }

    /// <summary>Composer Ultracode switch.</summary>
    public bool Ultracode { get; init; }

    /// <summary>The bridge home whose files the agent must not touch; null reads the environment.</summary>
    public string? BridgeHome { get; init; }
}

/// <summary>Headless argv for Claude Code.</summary>
public static class ClaudeArgv
{
    /// <summary>Permission modes Claude accepts.</summary>
    public static IReadOnlyList<string> PermissionModes { get; } =
        ["plan", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions"];

    /// <summary>The mode when the caller omits one.</summary>
    public const string DefaultPermissionMode = "acceptEdits";

    /// <summary>The deny rules Settings › Sudo off adds.</summary>
    public static IReadOnlyList<string> SudoDenied { get; } = ["Bash(sudo:*)", "Bash(pkexec:*)", "Bash(doas:*)"];

    private const string TokenFile = "gateway-token";
    private const string OwnerTokenFile = "gateway-owner-token";
    private const string HomeEnv = "AGENT_CLI_BRIDGE_HOME";

    /// <summary>A known mode; an unknown one must not fall through to a mode that can edit, so it becomes plan.</summary>
    public static string NormalizePermissionMode(string? mode)
    {
        if (mode is null) return DefaultPermissionMode;
        var raw = mode.Trim();
        return PermissionModes.Contains(raw) ? raw : "plan";
    }

    /// <summary>The <c>--permission-mode</c> flags; bypass adds the companion skip flag.</summary>
    public static List<string> PermissionArgs(string? mode)
    {
        var m = NormalizePermissionMode(mode);
        List<string> args = ["--permission-mode", m];
        if (m == "bypassPermissions") args.Add("--dangerously-skip-permissions");
        return args;
    }

    /// <summary>The <c>--model</c> flags; an id starting with '-' would be read as a flag and throws.</summary>
    public static List<string> ModelArgs(string? model)
    {
        var id = model?.Trim();
        if (string.IsNullOrEmpty(id)) return [];
        if (id.StartsWith('-'))
            throw new ArgumentException($"a model id cannot start with '-': {(id.Length > 40 ? id[..40] : id)}");
        string[] placeholders = ["default", "claude code", "cursor agent", "google antigravity", "gemini cli"];
        return placeholders.Contains(id.ToLowerInvariant()) ? [] : ["--model", id];
    }

    /// <summary>
    /// <c>--allowedTools</c> for a mode. Null is the default list: a non-live turn keeps Bash and Read plus
    /// Edit and Write outside plan and manual; a live turn omits Bash. A list replaces it, comma-joined
    /// (a rule with a comma throws); an empty list adds none.
    /// </summary>
    public static List<string> AllowedToolsArgs(string mode, IReadOnlyList<string>? allowed, bool liveInput)
    {
        if (allowed is null)
        {
            var readOnly = mode is "plan" or "manual";
            var tools = liveInput
                ? (readOnly ? "Read" : "Read,Edit,Write")
                : (readOnly ? "Bash,Read" : "Bash,Read,Edit,Write");
            return ["--allowedTools", tools];
        }
        if (allowed.Any(r => r.Contains(',')))
            throw new ArgumentException($"an allowed_tools rule cannot contain a comma: [{string.Join(", ", allowed)}]");
        return allowed.Count > 0 ? ["--allowedTools", string.Join(',', allowed)] : [];
    }

    /// <summary>The bridge home path, without creating it: the environment value, else <c>~/.agent-cli-bridge</c>.</summary>
    public static string BridgeHomePath()
    {
        var explicitHome = Environment.GetEnvironmentVariable(HomeEnv)?.Trim();
        return !string.IsNullOrEmpty(explicitHome) ? ExpandUser(explicitHome) : Path.Combine(UserHome(), ".agent-cli-bridge");
    }

    /// <summary>
    /// Deny rules that keep the agent off the bridge home and the gateway's token files. A deny rule beats
    /// every allow rule; the real boundary is that the CLI's directory is outside the bridge home.
    /// </summary>
    public static List<string> TokenFileDenials(string? home = null)
    {
        var expanded = ExpandUser(home ?? BridgeHomePath());
        var folder = expanded.Replace('\\', '/').TrimEnd('/');
        var spellings = new SortedSet<string>(StringComparer.Ordinal) { folder, expanded };
        var userHome = UserHome().Replace('\\', '/').TrimEnd('/');
        if (folder.StartsWith(userHome + "/", StringComparison.Ordinal))
        {
            var relative = folder[(userHome.Length + 1)..];
            spellings.Add($"~/{relative}");
            spellings.Add($"$HOME/{relative}");
            spellings.Add($"${{HOME}}/{relative}");
        }
        var rules = new List<string>();
        foreach (var tool in new[] { "Read", "Edit", "Write" }) rules.Add($"{tool}({RulePath(folder)}/**)");
        foreach (var name in new[] { TokenFile, OwnerTokenFile })
        {
            rules.Add($"Read(**/{name})");
            rules.Add($"Bash(*{name}*)");
        }
        foreach (var s in spellings)
        {
            rules.Add($"Bash(*{s})");
            rules.Add($"Bash(*{s}/*)");
            rules.Add($"Bash(*{s} *)");
        }
        var leaf = folder[(folder.LastIndexOf('/') + 1)..];
        if (leaf.Contains("agent-cli-bridge", StringComparison.OrdinalIgnoreCase))
        {
            rules.Add($"Bash(*{leaf}/*)");
            rules.Add($"Bash(*/{leaf})");
            rules.Add($"Bash(*/{leaf} *)");
        }
        return rules.Where(r => !r.Contains(',')).ToList();
    }

    /// <summary>The headless argv for one Claude turn.</summary>
    public static List<string> Build(ClaudeArgvRequest r)
    {
        var mode = NormalizePermissionMode(r.PermissionMode);
        var argv = new List<string> { r.Binary, "-p" };
        if (r.LiveInput)
            argv.AddRange(["--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--replay-user-messages", "--permission-prompt-tool", "stdio"]);
        else
            argv.AddRange(["--output-format", "stream-json", "--verbose", "--include-partial-messages"]);
        argv.AddRange(ModelArgs(r.Model));
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.AddRange(["--resume", r.ResumeId]);
        if (r.SystemText.Length > 0) argv.AddRange(["--append-system-prompt", r.SystemText]);
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(AllowedToolsArgs(mode, r.AllowedTools, r.LiveInput));
        argv.AddRange(["--disallowedTools", string.Join(',', TokenFileDenials(r.BridgeHome))]);
        argv.AddRange(Effort.Args("claude", r.Effort, r.Ultracode, r.Model));
        if (!r.AllowSudo) argv.AddRange(["--disallowedTools", string.Join(',', SudoDenied)]);
        argv.AddRange(r.CliArgs);
        // Last, after "--", so a prompt starting with "-" is never read as a flag.
        if (!r.LiveInput && !r.PromptOnStdin) argv.AddRange(["--", r.Prompt]);
        return argv;
    }

    private static string UserHome() => Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

    private static string ExpandUser(string path) =>
        path == "~" ? UserHome() : path.StartsWith("~/", StringComparison.Ordinal) ? Path.Combine(UserHome(), path[2..]) : path;

    /// <summary>An absolute path as Claude's permission rules spell it: "//" then POSIX form.</summary>
    private static string RulePath(string posix)
    {
        if (posix.Length > 1 && posix[1] == ':') posix = $"/{char.ToLowerInvariant(posix[0])}{posix[2..]}";
        return posix.StartsWith('/') ? "/" + posix : "//" + posix;
    }
}
