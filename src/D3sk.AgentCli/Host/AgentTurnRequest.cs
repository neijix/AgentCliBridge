using D3sk.AgentCli.Accounts;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Security;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Host;

/// <summary>One headless turn of a CLI: what <see cref="AgentTurn.RunAsync"/> runs.</summary>
public sealed record AgentTurnRequest
{
    /// <summary>A command or alias of <see cref="AgentRegistry"/>; an unknown one runs as a claude-flavored command by that name.</summary>
    public required string Command { get; init; }

    /// <summary>The latest user message.</summary>
    public required string Prompt { get; init; }

    /// <summary>
    /// The environment the host passes the CLI; it replaces the parent's completely and is required.
    /// The bridge's gateway tokens are removed; a claude child also loses the variables that turn
    /// its transcript saving off.
    /// </summary>
    public required IReadOnlyDictionary<string, string> Env { get; init; }

    /// <summary>Appended to the system prompt for Claude, put ahead of the first message for the others.</summary>
    public string SystemText { get; init; } = "";

    /// <summary>The picker's model id.</summary>
    public string? Model { get; init; }

    /// <summary>The permission mode; null is acceptEdits, an unknown value is plan.</summary>
    public string? PermissionMode { get; init; }

    /// <summary>The session id a SessionUpdate gave the previous turn.</summary>
    public string? ResumeId { get; init; }

    /// <summary>Extra argv, after every flag the bridge builds.</summary>
    public IReadOnlyList<string> CliArgs { get; init; } = [];

    /// <summary>The project folder the CLI runs in.</summary>
    public string? Cwd { get; init; }

    /// <summary>Applied on top of <see cref="Env"/> after the removals, so the host's own choice wins.</summary>
    public IReadOnlyDictionary<string, string>? ExtraEnv { get; init; }

    /// <summary>An explicit binary; null resolves the command (see <see cref="BinaryResolver"/>).</summary>
    public string? Binary { get; init; }

    /// <summary>Finds the binary when <see cref="Binary"/> is null; null uses <see cref="AgentRegistry.ResolveBinary"/>.</summary>
    public Func<string, string?>? BinaryResolver { get; init; }

    /// <summary>Also yield thinking and tool events, not only text.</summary>
    public bool Activity { get; init; }

    /// <summary>Claude only: <c>--allowedTools</c> rules replacing the default list; empty adds none.</summary>
    public IReadOnlyList<string>? AllowedTools { get; init; }

    /// <summary>Claude only, Settings › Sudo; off (the default) disallows sudo, pkexec and doas.</summary>
    public bool AllowSudo { get; init; }

    /// <summary>Composer effort level (Claude, Copilot); unknown or "auto" adds no flag.</summary>
    public string? Effort { get; init; }

    /// <summary>Claude only: the composer's Ultracode switch.</summary>
    public bool Ultracode { get; init; }

    /// <summary>Claude only: the bridge home whose files the agent must not touch; null reads the environment.</summary>
    public string? BridgeHome { get; init; }

    /// <summary>The account rules to apply for this command and folder; null leaves the CLI on its default login.</summary>
    public ClaudeAccounts? Accounts { get; init; }

    /// <summary>A folder of shims put first on the child's PATH.</summary>
    public string? ShimFolder { get; init; }

    /// <summary>Timings of the run; null uses the defaults. Its <see cref="ChildRunOptions.Deadline"/> is shared with the output parser.</summary>
    public ChildRunOptions? Run { get; init; }

    /// <summary>
    /// Claude only: lets the host answer tool approvals and add messages while the turn runs; the turn then yields
    /// <c>ApprovalRequest</c>, <c>InputAccepted</c> and <c>ModeChanged</c>. Another CLI gets it closed.
    /// </summary>
    public TurnInput? Input { get; init; }

    /// <summary>
    /// The prompt-injection defense for this turn, one instance per turn; null with <see cref="NoGuard"/> false
    /// is a default <see cref="InjectionGuard"/>. It appends its policy to the system text and needs the tool events.
    /// </summary>
    public InjectionGuard? Guard { get; init; }

    /// <summary>Turns the injection guard off.</summary>
    public bool NoGuard { get; init; }

    /// <summary>
    /// Claude only: the web policy (web through D3SKWEBSCOUT only); null with <see cref="NoWebScout"/> false is a
    /// default <see cref="ScoutPolicy"/>.
    /// </summary>
    public ScoutPolicy? WebScout { get; init; }

    /// <summary>Turns the web policy off: Claude keeps its own WebSearch and WebFetch.</summary>
    public bool NoWebScout { get; init; }

    /// <summary>Where security stops are written; null with <see cref="NoSecurityLog"/> false is the default <see cref="Security.SecurityLog"/>.</summary>
    public SecurityLog? SecurityLog { get; init; }

    /// <summary>Writes no security log for this turn.</summary>
    public bool NoSecurityLog { get; init; }
}
