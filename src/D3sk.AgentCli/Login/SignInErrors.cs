using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Login;

/// <summary>Tells whether an agent's reply is a signed-out error, so the desk can offer "Sign in again" under it.</summary>
public static partial class SignInErrors
{
    /// <summary>A longer reply that merely quotes the phrase is not a sign-in error.</summary>
    public const int ErrorMax = 500;

    private static readonly (Regex Pattern, string[] Commands)[] Errors =
    [
        (OAuthExpired(), ["claude"]),
        (CursorLogin(), ["cursor-agent", "agent"]),
        (GrokLogin(), ["grok"]),
        (OpenCodeLogin(), ["opencode"]),
        (CopilotLogin(), ["copilot"]),
    ];

    [GeneratedRegex(@"OAuth session expired|could not be refreshed|Login expired|run ['""]?/login['""]?|profile login expired", RegexOptions.IgnoreCase)]
    private static partial Regex OAuthExpired();

    [GeneratedRegex(@"\bagent login\b|CURSOR_API_KEY", RegexOptions.IgnoreCase)]
    private static partial Regex CursorLogin();

    [GeneratedRegex(@"grok login|You are not authenticated", RegexOptions.IgnoreCase)]
    private static partial Regex GrokLogin();

    [GeneratedRegex(@"No auth credentials found|opencode auth login", RegexOptions.IgnoreCase)]
    private static partial Regex OpenCodeLogin();

    [GeneratedRegex(@"No authentication information found|\bcopilot login\b", RegexOptions.IgnoreCase)]
    private static partial Regex CopilotLogin();

    /// <summary>The reply's text: its content, else its text parts joined by newlines.</summary>
    public static string TextFrom(string? content, IEnumerable<(string Type, string? Text)>? parts = null)
    {
        if (!string.IsNullOrWhiteSpace(content))
        {
            return content.Trim();
        }
        return string.Join('\n', (parts ?? []).Where(p => p.Type == "text").Select(p => p.Text ?? "")).Trim();
    }

    /// <summary>
    /// The CLI to sign in for a signed-out error, else "". The reply's own <paramref name="command"/>
    /// wins when the error belongs to it; otherwise the first CLI among <paramref name="available"/>
    /// that the error names; with no agents known yet, the error's first CLI.
    /// </summary>
    public static string CommandFor(string? text, string? command, IReadOnlyCollection<string>? available)
    {
        var body = (text ?? "").Trim();
        if (body.Length == 0 || body.Length > ErrorMax)
        {
            return "";
        }
        foreach (var (pattern, commands) in Errors)
        {
            if (!pattern.IsMatch(body))
            {
                continue;
            }
            if (command is not null && commands.Contains(command))
            {
                return command;
            }
            var known = available ?? [];
            return commands.FirstOrDefault(known.Contains) ?? (known.Count == 0 ? commands[0] : "");
        }
        return "";
    }
}
