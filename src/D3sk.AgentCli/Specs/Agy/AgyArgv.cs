using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Agy;

/// <summary>One Antigravity turn's inputs to <see cref="AgyArgv.Build"/>.</summary>
public sealed record AgyArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt.</summary>
    public string Prompt { get; init; } = "";

    /// <summary>The conversation id to resume (the id the stream's init event carried).</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }

    /// <summary>The project folder, repeated as <c>--add-dir</c>: <c>agy -p</c> does not treat the process cwd as the workspace.</summary>
    public string? Cwd { get; init; }
}

/// <summary>Headless argv for the Antigravity CLI (<c>agy -p</c>).</summary>
public static class AgyArgv
{
    /// <summary>
    /// The <c>--mode</c> flags. Plan is plan. Bypass is accept-edits plus the skip flag.
    /// Auto and don't-ask are <c>auto</c>: accept-edits still asks before a terminal command, and print mode
    /// cannot ask, so it soft-denies the command. Accept edits stays accept-edits (shell still asks).
    /// </summary>
    public static List<string> PermissionArgs(string? mode) => ClaudeArgv.NormalizePermissionMode(mode) switch
    {
        "bypassPermissions" => ["--mode", "accept-edits", "--dangerously-skip-permissions"],
        "plan" => ["--mode", "plan"],
        "auto" or "dontAsk" => ["--mode", "auto"],
        _ => ["--mode", "accept-edits"],
    };

    /// <summary>The headless argv for one Antigravity turn.</summary>
    public static List<string> Build(AgyArgvRequest r)
    {
        var argv = new List<string> { r.Binary, "-p", r.Prompt, "--output-format", "stream-json" };
        argv.AddRange(ClaudeArgv.ModelArgs(r.Model));
        // Without --conversation every turn is a fresh session.
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.AddRange(["--conversation", r.ResumeId]);
        argv.AddRange(PermissionArgs(r.PermissionMode));
        if (!string.IsNullOrEmpty(r.Cwd)) argv.AddRange(["--add-dir", r.Cwd]);
        argv.AddRange(r.CliArgs);
        return argv;
    }
}
