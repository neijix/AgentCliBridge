using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.OpenCode;

/// <summary>One OpenCode turn's inputs to <see cref="OpenCodeArgv.Build"/>.</summary>
public sealed record OpenCodeArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt, already composed.</summary>
    public string Prompt { get; init; } = "";

    /// <summary>The session id to resume.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's <c>provider/model</c> id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }
}

/// <summary>
/// Headless argv for OpenCode (<c>run --format json</c>). The project is the process cwd, never a
/// flag: OpenCode 2 rejects <c>--dir</c>; <see cref="OpenCodeEnvironment.Directory"/> also sets PWD.
/// </summary>
public static class OpenCodeArgv
{
    /// <summary>
    /// <c>opencode run</c> rejects any tool call that would ask for approval, and the turn then ends
    /// without an answer. Plan and manual use its built-in read-only <c>plan</c> agent; the default
    /// <c>build</c> agent asks nothing inside the project; bypass also approves the rest.
    /// </summary>
    public static List<string> PermissionArgs(string? mode) => ClaudeArgv.NormalizePermissionMode(mode) switch
    {
        "plan" or "manual" => ["--agent", "plan"],
        "bypassPermissions" => ["--auto"],
        _ => [],
    };

    /// <summary>The headless argv for one OpenCode turn; the prompt follows <c>--</c> so a leading dash is not a flag.</summary>
    public static List<string> Build(OpenCodeArgvRequest r)
    {
        var argv = new List<string> { r.Binary, "run", "--format", "json", "--thinking" };
        argv.AddRange(ClaudeArgv.ModelArgs(r.Model));
        if (!string.IsNullOrEmpty(r.ResumeId)) argv.AddRange(["--session", r.ResumeId]);
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(r.CliArgs);
        argv.AddRange(["--", r.Prompt]);
        return argv;
    }
}
