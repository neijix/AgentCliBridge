using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Specs.Gemini;

/// <summary>One Gemini turn's inputs to <see cref="GeminiArgv.Build"/>.</summary>
public sealed record GeminiArgvRequest
{
    /// <summary>The binary to run.</summary>
    public required string Binary { get; init; }

    /// <summary>The user's prompt, already composed (see <see cref="GeminiArgv.ComposePrompt"/>).</summary>
    public string Prompt { get; init; } = "";

    /// <summary>Extra argv, after every flag built here.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }
}

/// <summary>Headless argv for Gemini CLI (<c>-p</c> with stream-json, docs/cli/headless.md). It has no resume flag.</summary>
public static class GeminiArgv
{
    /// <summary><c>--approval-mode</c>: plan (read-only) for plan and manual, yolo (auto-approve) for the rest.</summary>
    public static List<string> PermissionArgs(string? mode) =>
        ClaudeArgv.NormalizePermissionMode(mode) is "plan" or "manual"
            ? ["--approval-mode", "plan"]
            : ["--approval-mode", "yolo"];

    /// <summary>
    /// The prompt Gemini gets: it has no system-prompt flag, so the system text goes ahead of the user
    /// message on the first turn; a resumed session already carries it in the CLI's own history.
    /// </summary>
    public static string ComposePrompt(string latestUser, string systemText, string? resumeId) =>
        !string.IsNullOrEmpty(resumeId) || systemText.Length == 0 ? latestUser : $"{systemText}\n\n{latestUser}";

    /// <summary>The headless argv for one Gemini turn; <c>--skip-trust</c> avoids the interactive workspace-trust prompt.</summary>
    public static List<string> Build(GeminiArgvRequest r)
    {
        var argv = new List<string> { r.Binary, "-p", r.Prompt, "--output-format", "stream-json", "--skip-trust" };
        argv.AddRange(ClaudeArgv.ModelArgs(r.Model));
        argv.AddRange(PermissionArgs(r.PermissionMode));
        argv.AddRange(r.CliArgs);
        return argv;
    }
}
