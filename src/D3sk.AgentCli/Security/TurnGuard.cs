using System.Runtime.CompilerServices;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Security;

/// <summary>
/// The guard around one turn's host stream: answers approvals the runner can settle itself, feeds the recorder and
/// the injection guard, and stops a non-live turn on its first high-severity finding.
/// </summary>
/// <remarks>
/// On a live Claude turn the default tool list does not pre-approve Bash. While the turn is still clean the runner
/// allows generic Bash, one plain scout search, one plain status and one plain fetch, without yielding the approval;
/// a path, a chain, <c>--allow-risky</c> and every other tool go to the host. Once tainted, <see cref="InjectionGuard.Review"/>
/// denies whatever is not read-only. On a non-live turn nothing can answer an approval, so the first HIGH finding kills
/// the CLI's process tree before the error is yielded, then <see cref="Completed"/> with -1 ends the turn; two LOW
/// findings only taint a live turn.
/// </remarks>
internal sealed class TurnGuard(
    InjectionGuard? guard, ScoutPolicy? scout, TurnRecorder? recorder, TurnInput? input, bool isLive, bool activity)
{
    /// <summary>The message of the error that ends a non-live turn after a high-severity finding.</summary>
    internal const string NonLiveHighMessage = "Stopped this turn: a tool result matched a high-severity prompt-injection rule.";

    /// <summary>The error code of that stop.</summary>
    internal const string InjectionCode = "injection";

    /// <summary>Yields the turn; disposing the source (the kill) happens before a stop's error is yielded.</summary>
    internal async IAsyncEnumerable<StreamEvent> Events(IAsyncEnumerable<StreamEvent> source, [EnumeratorCancellation] CancellationToken ct = default)
    {
        await using var events = source.GetAsyncEnumerator(ct);
        while (await events.MoveNextAsync().ConfigureAwait(false))
        {
            var current = events.Current;
            if (current is ApprovalRequest approval && input is not null)
            {
                var (blocked, allowed) = Settle(approval, input);
                if (blocked is not null)
                {
                    yield return recorder?.Blocked(blocked) ?? blocked;
                    continue;
                }
                if (allowed)
                {
                    continue;
                }
            }
            recorder?.Observe(current);
            var detection = guard?.Observe(current);
            if (activity || current is not (ThinkingDelta or ToolCall or ToolResult))
            {
                yield return current;
            }
            if (detection is null)
            {
                continue;
            }
            if (recorder is not null && !(detection.Rules.Count == 1 && detection.Rules[0] == InjectionGuard.PageWithheldRule))
            {
                detection = recorder.Detected(detection); // a withheld page is logged as page_withheld already
            }
            if (activity)
            {
                yield return detection;
            }
            if (StopsTurn(detection))
            {
                await events.DisposeAsync().ConfigureAwait(false); // the child is dead before the caller sees the error
                yield return new StreamError(NonLiveHighMessage, InjectionCode);
                yield return new Completed(-1);
                yield break;
            }
        }
    }

    /// <summary>Denies a tainted non-safe tool, or allows a clean-turn Bash form; anything else is the host's.</summary>
    private (ActionBlocked? Blocked, bool Allowed) Settle(ApprovalRequest approval, TurnInput turn)
    {
        var blocked = guard?.Review(approval);
        if (blocked is not null && turn.Answer(approval.RequestId, false, blocked.Reason))
        {
            return (blocked, false);
        }
        var clean = guard is null || !guard.IsTainted;
        return (null, clean && AutoAllowed(approval) && turn.Answer(approval.RequestId, true));
    }

    /// <summary>Generic Bash, one plain search or status, or a plain fetch the scout accepts; text naming the scout otherwise stays with the host.</summary>
    private bool AutoAllowed(ApprovalRequest approval)
    {
        if (ScoutCalls.ShellCommand(approval.Name, approval.Arguments) is not { } command)
        {
            return false;
        }
        if (ScoutCalls.IsPlainSearch(command) || ScoutCalls.IsPlainStatus(command) || scout?.IsScoutFetchApproval(approval) == true)
        {
            return true;
        }
        return ScoutCalls.PlainVerb(command) is null && !ScoutCalls.InvokesScout(command);
    }

    private bool StopsTurn(InjectionDetected detection)
    {
        if (isLive)
        {
            return false;
        }
        var high = (guard?.Rules ?? InjectionScanner.Rules).Where(r => r.Severity == Severity.High).Select(r => r.Name).ToHashSet();
        return detection.Rules.Any(high.Contains);
    }
}
