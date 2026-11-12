using System.Diagnostics;

namespace D3sk.AgentCli.Install;

/// <summary>What one command printed and how it ended.</summary>
/// <param name="ExitCode">The exit code; -1 when it never started or was stopped at the timeout.</param>
/// <param name="Output">The tail of stdout then stderr, or why it could not run.</param>
public sealed record ProcessResult(int ExitCode, string Output);

/// <summary>Runs one argv, never through a shell.</summary>
public interface IProcessRunner
{
    /// <summary>Run <paramref name="argv"/> (program first) and wait for it.</summary>
    Task<ProcessResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct);
}

/// <summary>The real runner: an argv list, stdin closed, the program's folder first on PATH.</summary>
public sealed class SystemProcessRunner : IProcessRunner
{
    private const int OutputTail = 4000;

    /// <inheritdoc />
    public async Task<ProcessResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct)
    {
        var info = new ProcessStartInfo(argv[0])
        {
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var arg in argv.Skip(1))
        {
            info.ArgumentList.Add(arg);
        }
        // A LaunchAgent starts with a bare PATH: npm needs the `node` beside it, brew its own bin.
        var folder = Path.GetDirectoryName(argv[0]);
        if (!string.IsNullOrEmpty(folder))
        {
            info.Environment["PATH"] = folder + Path.PathSeparator + (Environment.GetEnvironmentVariable("PATH") ?? "");
        }
        info.Environment.TryAdd("HOMEBREW_NO_ENV_HINTS", "1");
        try
        {
            using var process = Process.Start(info) ?? throw new InvalidOperationException("no process");
            process.StandardInput.Close();
            var stdout = process.StandardOutput.ReadToEndAsync(CancellationToken.None);
            var stderr = process.StandardError.ReadToEndAsync(CancellationToken.None);
            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(timeout);
            try
            {
                await process.WaitForExitAsync(limit.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                process.Kill(entireProcessTree: true);
                ct.ThrowIfCancellationRequested();
                return new ProcessResult(-1, $"Gave up after {timeout.TotalSeconds:F0}s.");
            }
            var text = $"{await stdout.ConfigureAwait(false)}\n{await stderr.ConfigureAwait(false)}".Trim();
            return new ProcessResult(process.ExitCode, text.Length > OutputTail ? text[^OutputTail..] : text);
        }
        catch (Exception ex) when (ex is System.ComponentModel.Win32Exception or InvalidOperationException or IOException)
        {
            return new ProcessResult(-1, $"Could not start {argv[0]}: {ex.Message}");
        }
    }
}
