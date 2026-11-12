using System.Diagnostics;

namespace D3sk.AgentCli.Status;

/// <summary>What a short probe process printed and how it ended.</summary>
/// <param name="ExitCode">The exit code.</param>
/// <param name="Stdout">Standard output.</param>
/// <param name="Stderr">Standard error.</param>
public sealed record ProbeResult(int ExitCode, string Stdout, string Stderr);

/// <summary>Runs one short child process (no shell, no window, no stdin) and waits for it, or kills it.</summary>
public static class ProbeProcess
{
    /// <summary>
    /// Starts <paramref name="argv"/>, closes its stdin and reads both outputs. A process still
    /// running after <paramref name="timeout"/> is killed with its children and a
    /// <see cref="TimeoutException"/> says so. A program that cannot start throws a
    /// <see cref="System.ComponentModel.Win32Exception"/>.
    /// </summary>
    public static async Task<ProbeResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct)
    {
        var info = new ProcessStartInfo(argv[0])
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var arg in argv.Skip(1))
        {
            info.ArgumentList.Add(arg);
        }
        using var process = Process.Start(info) ?? throw new InvalidOperationException($"could not start {argv[0]}");
        process.StandardInput.Close();
        var stdout = process.StandardOutput.ReadToEndAsync(CancellationToken.None);
        var stderr = process.StandardError.ReadToEndAsync(CancellationToken.None);
        using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
        limit.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(limit.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            Kill(process);
            throw new TimeoutException($"{Path.GetFileName(argv[0])} timed out after {timeout.TotalSeconds:0} seconds");
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            throw;
        }
        return new ProbeResult(process.ExitCode, await stdout.ConfigureAwait(false), await stderr.ConfigureAwait(false));
    }

    private static void Kill(Process process)
    {
        try
        {
            process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException)
        {
            // It ended between the timeout and the kill.
        }
    }
}
