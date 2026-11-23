using System.Text.Json.Nodes;
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

    /// <summary>True while the latest <c>background_tasks_changed</c> lists any task, of any kind (the background wait's "open").</summary>
    public bool HasOpenTasks { get; set; }

    private readonly Dictionary<string, string> _runIds = [];
    private readonly List<(string TaskId, string RunId)> _notices = [];

    /// <summary>
    /// True while a finished task's <c>task_notification</c> is not yet taken up by the CLI's reply to it (the echo of the notice
    /// inside a reply, or the follow-up's own <c>result</c>). A <c>result</c> that comes while one is pending is followed by
    /// that reply, even when the task list is already empty.
    /// </summary>
    public bool NoticePending => _notices.Count > 0;

    /// <summary>Remembers the id and run id of every task a <c>background_tasks_changed</c> lists: only those get a notice that waits for a reply.</summary>
    public void Listed(JsonArray? tasks)
    {
        foreach (var task in (tasks ?? []).OfType<JsonObject>())
        {
            if (Json.AsString(task["task_id"]) is { Length: > 0 } id)
            {
                _runIds[id] = Json.AsString(task["run_id"]) ?? "";
            }
        }
    }

    /// <summary>
    /// A <c>task_notification</c>. It waits for a reply only when its task was listed open (a foreground command has a notice and
    /// no listing, and the CLI answers none) and its status is not <c>stopped</c> (the model stopped the task itself: the notice
    /// comes with no follow-up turn), and a task already pending counts once. Its run id is the line's, else the listing's.
    /// </summary>
    public void Notice(JsonObject line)
    {
        var id = Json.AsString(line["task_id"]) ?? "";
        if (!_runIds.TryGetValue(id, out var listedRun) || Json.AsString(line["status"]) == "stopped" || _notices.Any(n => n.TaskId == id))
        {
            return;
        }

        _notices.Add((id, Json.AsString(line["run_id"]) is { Length: > 0 } run ? run : listedRun));
    }

    /// <summary>
    /// The reply to a notice (its echo, or its follow-up's <c>result</c>) takes it: the notice whose run is <paramref name="runId"/>
    /// when the line names one, else the oldest. A named run with no pending notice takes none.
    /// </summary>
    public void TakeNotice(string? runId)
    {
        var at = string.IsNullOrEmpty(runId) ? 0 : _notices.FindIndex(n => n.RunId == runId);
        if (at >= 0 && at < _notices.Count)
        {
            _notices.RemoveAt(at);
        }
    }

    /// <summary>True once any text of the turn was shown, in an earlier reply or this one.</summary>
    public bool ShownText { get; set; }

    /// <summary>True from the end of a reply that began or continued the wait until the next reply's first text, which a paragraph break precedes.</summary>
    public bool BreakBeforeText { get; set; }
}
