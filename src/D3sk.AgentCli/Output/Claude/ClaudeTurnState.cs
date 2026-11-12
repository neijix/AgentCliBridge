using D3sk.AgentCli.Output.Common;

namespace D3sk.AgentCli.Output.Claude;

/// <summary>What one parsed Claude-protocol turn remembers between lines.</summary>
public sealed class ClaudeTurnState
{
    /// <summary>The session id already emitted.</summary>
    public SessionIds Sessions { get; } = new();

    /// <summary>True once text or an error was shown, so a result's fallback text would repeat it.</summary>
    public bool Seen { get; set; }

    /// <summary>True while <c>background_tasks_changed</c> lists a subagent or workflow the CLI still waits for.</summary>
    public bool HasBackgroundAgents { get; set; }
}
