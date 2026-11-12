using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Specs.Copilot;

/// <summary>One Copilot turn's inputs to <see cref="CopilotArgv.Build"/>.</summary>
public sealed record CopilotArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt, already composed with any system text (Copilot has no system-prompt flag).</summary>
    public string Prompt { get; init; } = "";

    /// <summary>The session id to resume.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }

    /// <summary>Composer effort level; unknown or "auto" adds no flag.</summary>
    public string? Effort { get; init; }
}

/// <summary>Headless argv for GitHub Copilot CLI.</summary>
public static class CopilotArgv
{
    /// <summary>Permission modes the bridge accepts (shared by every CLI).</summary>
    public static IReadOnlyList<string> PermissionModes { get; } =
        ["plan", "manual", "acceptEdits", "auto", "dontAsk", "bypassPermissions"];

    /// <summary>The mode when the caller omits one.</summary>
    public const string DefaultPermissionMode = "acceptEdits";

    /// <summary>A known mode; an unknown one must not fall through to a mode that can edit, so it becomes plan.</summary>
    public static string NormalizePermissionMode(string? mode)
    {
        if (mode is null) return DefaultPermissionMode;
        var raw = mode.Trim();
        return PermissionModes.Contains(raw) ? raw : "plan";
    }

    /// <summary>
    /// <c>--plan</c> starts read-only plan mode; every other mode gets <c>--allow-all-tools</c>, which
    /// non-interactive mode needs for any tool use.
    /// </summary>
    public static List<string> PermissionArgs(string? mode) =>
        NormalizePermissionMode(mode) == "plan" ? ["--plan"] : ["--allow-all-tools"];

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
    /// The headless argv for one Copilot turn: <c>-p</c> and JSONL events. <c>--no-ask-user</c> because a
    /// headless host cannot answer the ask_user tool; logging and auto-update off keep stdout pure JSONL.
    /// </summary>
    public static List<string> Build(CopilotArgvRequest r)
    {
        var argv = new List<string>
        {
            r.Binary, "-p", r.Prompt, "--output-format", "json", "--no-color", "--no-auto-update",
            "--log-level", "none", "--no-ask-user",
        };
        argv.AddRange(ModelArgs(r.Model));
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.Add($"--resume={r.ResumeId}");
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(Effort.Args("copilot", r.Effort));
        argv.AddRange(r.CliArgs);
        return argv;
    }
}
