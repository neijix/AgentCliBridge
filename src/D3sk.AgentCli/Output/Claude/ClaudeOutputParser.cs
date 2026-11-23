using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Output.Claude;

/// <summary>
/// Claude Code's stream-json stdout, which Gemini and Grok still share. On a live turn
/// (<paramref name="Live"/>) the control lines (<c>control_request</c>, <c>control_response</c>, echoed user
/// messages) go to <see cref="LiveLines"/> first; without it they are skipped like any line the parser does not know.
/// </summary>
/// <param name="Activity">Whether thinking and tool events are shown, not only text.</param>
/// <param name="AfterResult">Started when a result ends the turn and no background agent is still working; null for none.</param>
/// <param name="CancelledMessage">Grok's note for a result whose <c>stop_reason</c> is <c>cancelled</c>; null for the other CLIs.</param>
/// <param name="Live">The control-line reader of a live turn; null for a turn that takes no input.</param>
/// <param name="CloseInput">Closes the CLI's stdin once a live turn's result arrived with nothing left on the way.</param>
/// <param name="BackgroundWait">
/// Claude only: a result that comes while a task is listed open or a finished task's notice waits for its follow-up (failed or
/// not) begins or continues a wait (no deadline, input open) instead of ending the turn. A notice is taken by its echo or its
/// follow-up's result, never by an <c>init</c> or a result with no <c>origin</c>; a task listed open, a notice of an unlisted task
/// or of a task the model stopped does not count the same way (see <see cref="ClaudeTurnState.Notice"/>).
/// </param>
public sealed record ClaudeOutputParser(
    bool Activity = true, TurnDeadline? AfterResult = null, string? CancelledMessage = null, LiveLines? Live = null, Action? CloseInput = null,
    bool BackgroundWait = false) : IOutputParser
{
    /// <inheritdoc />
    public async IAsyncEnumerable<StreamEvent> ParseAsync(
        IAsyncEnumerable<ChildLine> lines, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var state = new ClaudeTurnState();
        await foreach (var line in JsonLine.ReadAsync(lines).WithCancellation(cancellationToken))
        {
            if (line.Value is not JsonObject lineEvent)
            {
                continue;
            }

            foreach (var piece in Handle(lineEvent, state))
            {
                yield return piece;
            }
        }
    }

    private IEnumerable<StreamEvent> Handle(JsonObject lineEvent, ClaudeTurnState state)
    {
        var type = Json.AsString(lineEvent["type"]);
        if (type == "result")
        {
            var cancelled = Json.AsString(lineEvent["stop_reason"]) == "cancelled" ? CancelledMessage : null;
            return ClaudeStream.Result(lineEvent, state, AfterResult, cancelled, Live, CloseInput, BackgroundWait);
        }

        var subtype = Json.AsString(lineEvent["subtype"]);
        if (type == "system" && subtype == "init")
        {
            return ClaudeStream.InitSession(lineEvent, state.Sessions);
        }

        if (type == "system" && subtype == "background_tasks_changed")
        {
            state.HasBackgroundAgents = ClaudeStream.RunsBackgroundAgents(lineEvent);
            state.HasOpenTasks = ClaudeStream.ListsOpenTasks(lineEvent);
            state.Listed(lineEvent["tasks"] as JsonArray);
            return [];
        }

        if (BackgroundWait && type == "system" && subtype == "task_notification")
        {
            state.Notice(lineEvent);
            return [];
        }

        if (BackgroundWait && type == "user" && ClaudeStream.IsTaskNotice(lineEvent))
        {
            state.TakeNotice(ClaudeStream.NoticeRun(lineEvent)); // the CLI's own echo of the notice: the reply under way took it, and it is not the user's message
            return [];
        }

        if (Live is not null && Live.TryHandle(lineEvent, out var control))
        {
            return control;
        }

        return type switch
        {
            "stream_event" => ClaudeStream.Deltas(lineEvent, Activity, state),
            "assistant" or "user" when Activity => ClaudeStream.ToolEvents(lineEvent),
            _ => [],
        };
    }
}
