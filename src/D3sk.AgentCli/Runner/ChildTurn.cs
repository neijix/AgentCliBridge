using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;

namespace D3sk.AgentCli.Runner;

/// <summary>Timings of one run; the defaults are the ones the Python bridge ships.</summary>
public sealed record ChildRunOptions
{
    /// <summary>
    /// The deadline the output parser starts when the CLI reports the end of its turn. Null makes
    /// the runner create one with <see cref="TurnDeadline.DefaultGrace"/>, started only when the
    /// CLI itself exits.
    /// </summary>
    public TurnDeadline? Deadline { get; init; }

    /// <summary>A ceiling on the whole run; past it the tree is killed and a <c>timeout</c> error ends the run.</summary>
    public TimeSpan? Timeout { get; init; }

    /// <summary>How long a CLI may keep running after its turn ended before its tree is killed.</summary>
    public TimeSpan ExitGrace { get; init; } = TimeSpan.FromSeconds(3);

    /// <summary>How often a read with no deadline checks whether the CLI exited.</summary>
    public TimeSpan ExitPoll { get; init; } = TimeSpan.FromSeconds(1);
}

/// <summary>
/// Starts one CLI, streams its stdout lines and reports how it ended.
/// </summary>
/// <remarks>
/// Cancellation is explicit: the token passed to <see cref="RunAsync"/> (Stop), or the consumer
/// abandoning the enumeration, kills the CLI's whole process tree and throws
/// <see cref="OperationCanceledException"/>. The runner knows no connection, so a host that loses
/// its client must simply not cancel: a lost connection never kills a CLI. A child that dies, or
/// fails to start, is reported as a <see cref="ChildError"/>, never as a hang.
/// </remarks>
public static class ChildTurn
{
    /// <summary>Runs <paramref name="command"/> and yields its lines, then possibly an error, then <see cref="ChildExited"/>.</summary>
    public static async IAsyncEnumerable<ChildEvent> RunAsync(
        ChildCommand command,
        ChildRunOptions? options = null,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(command);
        options ??= new ChildRunOptions();
        var deadline = options.Deadline ?? new TurnDeadline(TurnDeadline.DefaultGrace);

        var (process, failure) = Start(command);
        if (process is null)
        {
            command.LiveInput?.Close();
            yield return failure!;
            yield break;
        }

        using var _ = process;
        var stderr = new StderrTail(process.StandardError.BaseStream);
        FeedStdin(process, command);

        using var timeoutCts = new CancellationTokenSource();
        if (options.Timeout is { } limit)
        {
            timeoutCts.CancelAfter(limit);
        }
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);

        var lines = 0;
        var interrupted = true; // stays true if the consumer stops enumerating: Stop kills the tree
        try
        {
            await foreach (var bytes in LineReader.ReadAsync(
                process.StandardOutput.BaseStream, deadline, () => SafeHasExited(process), options.ExitPoll, linked.Token))
            {
                lines++;
                yield return new ChildLine(bytes);
            }
            interrupted = linked.IsCancellationRequested;
        }
        finally
        {
            command.LiveInput?.Close();
            if (interrupted)
            {
                ProcessTree.Kill(process);
            }
        }

        var (exitCode, stderrBytes) = await ReapAsync(process, stderr, deadline, interrupted, options).ConfigureAwait(false);
        if (ct.IsCancellationRequested)
        {
            throw new OperationCanceledException(ct);
        }
        var text = Encoding.UTF8.GetString(stderrBytes).Trim();
        if (timeoutCts.IsCancellationRequested)
        {
            yield return new ChildError("timeout", $"{command.FileName} did not finish within {options.Timeout}.");
        }
        else if (lines == 0 && exitCode != 0)
        {
            yield return new ChildError("child_died", text.Length > 0 ? text : $"{command.FileName} exited with status {exitCode}");
        }
        yield return new ChildExited(exitCode, text, deadline.Expired);
    }

    private static (Process? Process, ChildError? Error) Start(ChildCommand command)
    {
        var psi = new ProcessStartInfo(command.FileName)
        {
            WorkingDirectory = command.WorkingDirectory ?? "",
            UseShellExecute = false,
            CreateNoWindow = true, // Windows: keep the CLI off the desktop
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var arg in command.Arguments)
        {
            psi.ArgumentList.Add(arg);
        }
        psi.Environment.Clear(); // the host's allowlist, never the parent's
        foreach (var (key, value) in command.Environment)
        {
            psi.Environment[key] = value;
        }
        try
        {
            return (Process.Start(psi) ?? throw new InvalidOperationException("no process was started"), null);
        }
        catch (Win32Exception e) when (e.NativeErrorCode == 2 || e.NativeErrorCode == 3)
        {
            return (null, new ChildError("not_found", $"CLI agent binary not found: {command.FileName}"));
        }
        catch (Exception e)
        {
            return (null, new ChildError("spawn_failed", $"Failed to start {command.FileName}: {e.Message}"));
        }
    }

    private static void FeedStdin(Process process, ChildCommand command)
    {
        var stdin = process.StandardInput.BaseStream;
        if (command.LiveInput is { } live)
        {
            live.Bind(stdin);
            return;
        }
        try
        {
            if (command.StdinText is { } text)
            {
                stdin.Write(new UTF8Encoding(false).GetBytes(text)); // a lone surrogate becomes "?"-like U+FFFD
                stdin.Flush();
            }
            stdin.Dispose(); // end of input: a CLI reading stdin never blocks on our open pipe
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException)
        {
            // the CLI closed stdin first
        }
    }

    private static bool SafeHasExited(Process process)
    {
        try
        {
            return process.HasExited;
        }
        catch (InvalidOperationException)
        {
            return true;
        }
    }

    private static async Task<(int ExitCode, byte[] Stderr)> ReapAsync(
        Process process, StderrTail stderr, TurnDeadline deadline, bool interrupted, ChildRunOptions options)
    {
        // The stderr drain is skipped after an interrupt or an expired deadline: a surviving
        // child holding the pipe would block it.
        var stderrBytes = interrupted || deadline.Expired
            ? stderr.Snapshot()
            : await stderr.ReadAsync(deadline.Remaining()).ConfigureAwait(false);
        try
        {
            if (!deadline.Started && !interrupted)
            {
                await process.WaitForExitAsync().ConfigureAwait(false);
                return (process.ExitCode, stderrBytes);
            }
            await process.WaitForExitAsync().WaitAsync(options.ExitGrace).ConfigureAwait(false);
            return (process.ExitCode, stderrBytes);
        }
        catch (TimeoutException)
        {
            // Still running past its grace after the turn ended: stop it; the answer is complete.
            ProcessTree.Kill(process);
            try
            {
                await process.WaitForExitAsync().WaitAsync(options.ExitGrace).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                // the kernel has not reaped it yet
            }
            return (interrupted ? -1 : 0, stderrBytes);
        }
        catch (InvalidOperationException)
        {
            return (-1, stderrBytes);
        }
    }
}
