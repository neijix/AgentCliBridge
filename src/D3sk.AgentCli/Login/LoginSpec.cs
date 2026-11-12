namespace D3sk.AgentCli.Login;

/// <summary>How one CLI signs in: its commands, the environment that keeps it from opening a browser, and which links may be shown.</summary>
/// <param name="Login">Arguments of the sign-in command (the binary is the host's, never the request's).</param>
/// <param name="Status">Arguments of the status command; empty when <see cref="ReadsOwnStatus"/> is set.</param>
/// <param name="Logout">Arguments of the sign-out command; empty when the CLI has none.</param>
/// <param name="Env">Variables added to the CLI's environment so it never opens a browser on the host.</param>
/// <param name="Hosts">A link on another host is never handed to the browser.</param>
public sealed record LoginSpec(
    IReadOnlyList<string> Login,
    IReadOnlyList<string> Status,
    IReadOnlyList<string> Logout,
    IReadOnlyDictionary<string, string> Env,
    IReadOnlyList<string> Hosts)
{
    /// <summary>Stdin stays open so a pasted page code or key can finish the login.</summary>
    public bool ReadsCode { get; init; }

    /// <summary>What follows a pasted code (Open Router's password field submits on a carriage return).</summary>
    public string CodeEol { get; init; } = "\n\n";

    /// <summary>False for Open Router: a static keys page, no URL from the CLI.</summary>
    public bool NeedsLink { get; init; } = true;

    /// <summary>An https page on <see cref="Hosts"/> used when the CLI prints none.</summary>
    public string Page { get; init; } = "";

    /// <summary>The sign-in is read from the CLI's own files (Copilot has no status command), not from <see cref="Status"/>.</summary>
    public bool ReadsOwnStatus { get; init; }

    /// <summary>Set when the CLI has no logout command: what the owner runs instead.</summary>
    public string LogoutHint { get; init; } = "";
}

/// <summary>The CLIs that can be signed in from a host's page; Antigravity and Gemini have no headless login command.</summary>
public static class LoginSpecs
{
    private static readonly LoginSpec Cursor = new(
        ["login"], ["status"], ["logout"],
        new Dictionary<string, string> { ["NO_OPEN_BROWSER"] = "1" },
        ["cursor.com", "www.cursor.com"]);

    private static readonly IReadOnlyDictionary<string, string> NoBrowser =
        new Dictionary<string, string> { ["NO_OPEN_BROWSER"] = "1", ["BROWSER"] = "true" };

    private static readonly LoginSpec Claude = new(
        ["auth", "login", "--claudeai"], ["auth", "status"], ["auth", "logout"], NoBrowser,
        ["claude.com", "www.claude.com", "claude.ai"])
    {
        ReadsCode = true,
    };

    private static readonly LoginSpec Grok = new(
        ["login", "--device-auth"], ["models"], ["logout"], NoBrowser,
        ["auth.x.ai", "www.auth.x.ai", "grok.com", "www.grok.com"]);

    private static readonly LoginSpec Copilot = new([ "login", "--device-code"], [], [], NoBrowser, ["github.com"])
    {
        ReadsOwnStatus = true,
        LogoutHint = "Copilot CLI has no sign-out command — run copilot on that computer and type /logout",
    };

    private static readonly LoginSpec OpenRouter = new(
        ["auth", "login", "-p", "openrouter", "-m", "key"], ["auth", "list"], ["auth", "logout", "openrouter"], NoBrowser,
        ["openrouter.ai", "www.openrouter.ai"])
    {
        ReadsCode = true,
        CodeEol = "\r\n",
        NeedsLink = false,
        Page = "https://openrouter.ai/keys",
    };

    private static readonly Dictionary<string, LoginSpec> ByCommand = new(StringComparer.Ordinal)
    {
        ["agent"] = Cursor,
        ["cursor-agent"] = Cursor,
        ["claude"] = Claude,
        ["grok"] = Grok,
        ["opencode"] = OpenRouter,
        ["copilot"] = Copilot,
    };

    /// <summary>The spec of a CLI command, or null when this app cannot sign it in.</summary>
    public static LoginSpec? For(string command) => ByCommand.GetValueOrDefault(command);

    /// <summary>Whether the CLI can be signed in from a host's page.</summary>
    public static bool CanSignIn(string command) => ByCommand.ContainsKey(command);

    /// <summary>Claude's page and Open Router's keys page need a paste; Cursor, Grok and Copilot finish in the browser.</summary>
    public static bool NeedsCode(string command) => ByCommand.TryGetValue(command, out var spec) && spec.ReadsCode;
}
