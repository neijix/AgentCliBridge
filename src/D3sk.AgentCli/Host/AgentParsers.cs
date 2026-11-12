using D3sk.AgentCli.Output.Agy;
using D3sk.AgentCli.Output.Claude;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Output.Copilot;
using D3sk.AgentCli.Output.Cursor;
using D3sk.AgentCli.Output.Gemini;
using D3sk.AgentCli.Output.Grok;
using D3sk.AgentCli.Output.OpenCode;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Host;

/// <summary>The output parser of each adapter flavor.</summary>
internal static class AgentParsers
{
    /// <summary>The parser for a flavor; <paramref name="deadline"/> is the one the runner reads, <paramref name="status"/> Copilot's per-turn side channel, <paramref name="live"/> a live Claude turn's input.</summary>
    internal static IOutputParser For(string flavor, bool activity, TurnDeadline deadline, CopilotStatus? status, LiveTurn? live = null) => flavor switch
    {
        "cursor" => new CursorParser(activity, deadline),
        "antigravity" => new AgyOutputParser { Activity = activity },
        "gemini" => new GeminiOutputParser(activity, deadline),
        "grok" => new ClaudeOutputParser(activity, deadline, GrokOutputParser.CancelledMessage), // Grok's own parser has no deadline to share
        "copilot" => new CopilotParser(activity, status),
        "opencode" => new OpenCodeOutputParser(activity),
        _ => new ClaudeOutputParser(activity, deadline, null, live?.Lines, live is null ? null : live.CloseStdin),
    };
}
