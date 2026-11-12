using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Cursor;

/// <summary>One Cursor turn's inputs to <see cref="CursorArgv.Build"/>.</summary>
public sealed record CursorArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt, already composed (see <see cref="CursorArgv.ComposePrompt"/>).</summary>
    public string Prompt { get; init; } = "";

    /// <summary>The session id to resume.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }
}

/// <summary>Headless argv for Cursor Agent (<c>-p</c> with stream-json, https://cursor.com/docs/cli/headless).</summary>
public static class CursorArgv
{
    /// <summary>
    /// Cursor has no permission vocabulary: <c>--trust</c> covers workspace trust, and <c>--force</c>
    /// (the write path) is left out in plan and manual so the agent stays read-leaning.
    /// </summary>
    public static List<string> PermissionArgs(string? mode) =>
        ClaudeArgv.NormalizePermissionMode(mode) is "plan" or "manual" ? ["--trust"] : ["--trust", "--force"];

    /// <summary>
    /// The prompt Cursor gets: it has no system-prompt flag, so the system text goes ahead of the user
    /// message on the first turn; a resumed session already carries it in the CLI's own history.
    /// </summary>
    public static string ComposePrompt(string latestUser, string systemText, string? resumeId) =>
        !string.IsNullOrEmpty(resumeId) || systemText.Length == 0 ? latestUser : $"{systemText}\n\n{latestUser}";

    /// <summary>The headless argv for one Cursor turn.</summary>
    public static List<string> Build(CursorArgvRequest r)
    {
        var argv = new List<string> { r.Binary, "-p", r.Prompt, "--output-format", "stream-json", "--stream-partial-output" };
        argv.AddRange(ClaudeArgv.ModelArgs(r.Model));
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.AddRange(["--resume", r.ResumeId]);
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(r.CliArgs);
        return argv;
    }
}
