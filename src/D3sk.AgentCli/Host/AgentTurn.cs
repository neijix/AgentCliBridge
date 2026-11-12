using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Host;

/// <summary>The one entry that runs a turn of any CLI and returns its event stream.</summary>
public static class AgentTurn
{
    /// <summary>
    /// Runs one headless turn: resolves the CLI, builds its argv and environment, starts it, and yields
    /// <see cref="TextDelta"/>, <see cref="SessionUpdate"/> (persist it, pass it back as the next
    /// <see cref="AgentTurnRequest.ResumeId"/>) and the activity events when asked, then a
    /// <see cref="StreamError"/> when the turn produced no answer, then <see cref="Completed"/>.
    /// A CLI that is missing, refused or cannot start gives one <see cref="StreamError"/> and no <see cref="Completed"/>.
    /// </summary>
    /// <remarks>
    /// Cancelling the token (Stop) or abandoning the enumeration kills the CLI's whole process tree and
    /// throws <see cref="OperationCanceledException"/>. A host that loses its client simply does not
    /// cancel: a lost connection never kills a CLI. The guards (project roots, permission clamp) are the
    /// host's: this entry builds exactly the argv for the mode it is given.
    /// </remarks>
    /// <exception cref="ChildEnv.MissingChildEnvironmentException">The request carries no environment (thrown at the call).</exception>
    public static IAsyncEnumerable<StreamEvent> RunAsync(AgentTurnRequest request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        var launch = AgentLaunch.Prepare(request);
        if (launch.Command is null)
        {
            return Refused(launch);
        }
        var turn = Run(request, launch, cancellationToken);
        return launch.Watch is { } watch ? watch.Events(turn, cancellationToken) : turn;
    }

    private static async IAsyncEnumerable<StreamEvent> Refused(AgentLaunch launch)
    {
        yield return launch.Refusal!;
        await Task.CompletedTask;
    }

    private static async IAsyncEnumerable<StreamEvent> Run(
        AgentTurnRequest request, AgentLaunch launch, [EnumeratorCancellation] CancellationToken ct)
    {
        try
        {
            launch.Live?.Start(request.Prompt); // waits for the runner to bind the child's stdin
            await foreach (var e in Stream(request, launch, ct).WithCancellation(ct))
            {
                yield return e;
            }
        }
        finally
        {
            launch.Live?.Dispose(); // stdin closed, the host's input closed
        }
    }

    private static async IAsyncEnumerable<StreamEvent> Stream(
        AgentTurnRequest request, AgentLaunch launch, [EnumeratorCancellation] CancellationToken ct)
    {
        var options = (request.Run ?? new ChildRunOptions()) with { Deadline = launch.Deadline };
        await using var pump = new TurnPump(ChildTurn.RunAsync(launch.Command!, options, ct), ct);
        var seen = false; // the turn already yielded text or an in-band error
        await foreach (var e in launch.Parser!.ParseAsync(pump.LinesAsync(ct), ct).WithCancellation(ct))
        {
            seen |= e is TextDelta or StreamError;
            yield return e;
        }
        await pump.DrainAsync().ConfigureAwait(false);

        if (pump.Exited is null)
        {
            // the child never started: not_found or spawn_failed
            foreach (var error in pump.Errors)
            {
                yield return new StreamError(error.Message, error.Code);
            }
            yield break;
        }
        foreach (var error in pump.Errors.Where(x => x.Code is "timeout" or "read_failed"))
        {
            seen = true;
            yield return new StreamError(error.Message, error.Code);
        }
        var exit = pump.Exited;
        if (!seen)
        {
            yield return NoAnswer(request.Command, exit, launch.Status?.PendingError);
        }
        var code = launch.Status?.ResultExit ?? exit.ExitCode;
        yield return new Completed(code);
    }

    private static StreamError NoAnswer(string command, ChildExited exit, string? pendingError)
    {
        if (exit.ExitCode != 0)
        {
            return new StreamError(UnwrapJsonError(exit.Stderr, exit.Stderr.Length > 0 ? exit.Stderr : $"{command} exited with status {exit.ExitCode}"));
        }
        if (!string.IsNullOrEmpty(pendingError))
        {
            return new StreamError(pendingError); // an in-band failure while the process itself exits 0
        }
        if (exit.Stderr.Length > 0)
        {
            return new StreamError(UnwrapJsonError(exit.Stderr, exit.Stderr)); // a refused or rate-limited turn says why on stderr
        }
        return new StreamError(
            $"{command} exited cleanly with no output — the CLI produced nothing on stdout or stderr. Try again; if it repeats, " +
            "run the CLI in a terminal to see what it needs (auth, quota, or a config prompt).",
            "empty_output");
    }

    /// <summary>The human message of a CLI's JSON error object (<c>{error: {message}}</c> or <c>{error: "text"}</c>), else <paramref name="fallback"/>.</summary>
    internal static string UnwrapJsonError(string raw, string fallback)
    {
        try
        {
            if (JsonNode.Parse(raw) is JsonObject { } obj)
            {
                if (obj["error"] is JsonObject { } err && err["message"] is JsonValue { } m && m.TryGetValue<string>(out var text) && text.Length > 0)
                {
                    return text;
                }
                if (obj["error"] is JsonValue { } s && s.TryGetValue<string>(out var plain) && plain.Length > 0)
                {
                    return plain;
                }
            }
        }
        catch (JsonException)
        {
            // not JSON: the raw text is the message
        }
        return fallback;
    }
}
