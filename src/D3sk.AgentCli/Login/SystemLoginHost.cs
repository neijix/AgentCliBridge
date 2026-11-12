using System.ComponentModel;
using System.Collections;
using System.Diagnostics;
using System.Threading.Channels;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Login;

/// <summary>The real <see cref="ILoginHost"/>: <see cref="Process"/>, no window, no shell.</summary>
public sealed class SystemLoginHost : ILoginHost
{
    private const string QuarantineAttribute = "com.apple.quarantine";

    /// <inheritdoc />
    public IReadOnlyDictionary<string, string> Environment { get; } = Capture();

    /// <inheritdoc />
    public ILoginProcess Start(IReadOnlyList<string> argv, IReadOnlyDictionary<string, string> envOverlay, bool keepStdin)
    {
        var info = Info(argv);
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.Environment.Clear();
        foreach (var (key, value) in Environment.Concat(envOverlay).GroupBy(p => p.Key).Select(g => g.Last()))
        {
            info.Environment[key] = value;
        }
        return new SystemLoginProcess(Process.Start(info) ?? throw new IOException("The sign-in command did not start"), keepStdin);
    }

    /// <inheritdoc />
    public async Task<LoginCommandResult> RunAsync(IReadOnlyList<string> argv, TimeSpan timeout, CancellationToken ct)
    {
        var info = Info(argv);
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        using var process = Process.Start(info) ?? throw new IOException("The command did not start");
        using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
        limit.CancelAfter(timeout);
        var stdout = process.StandardOutput.ReadToEndAsync(limit.Token);
        var stderr = process.StandardError.ReadToEndAsync(limit.Token);
        try
        {
            await process.WaitForExitAsync(limit.Token).ConfigureAwait(false);
            return new LoginCommandResult(process.ExitCode, await stdout.ConfigureAwait(false), await stderr.ConfigureAwait(false));
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            ProcessTree.Kill(process);
            throw new TimeoutException($"{argv[0]} did not answer in {timeout.TotalSeconds:0} seconds");
        }
    }

    /// <inheritdoc />
    public void ClearQuarantine(string binary)
    {
        if (!OperatingSystem.IsMacOS() || binary.Length == 0)
        {
            return;
        }
        try
        {
            var target = File.ResolveLinkTarget(binary, returnFinalTarget: true)?.FullName ?? binary;
            var probe = Process.Start(Info(["/usr/bin/xattr", "-p", QuarantineAttribute, target]));
            probe?.WaitForExit(5000);
            if (probe is { ExitCode: 0 })
            {
                Process.Start(Info(["/usr/bin/xattr", "-d", QuarantineAttribute, target]))?.WaitForExit(5000);
            }
        }
        catch (Exception e) when (e is IOException or Win32Exception or InvalidOperationException)
        {
            // best effort: a CLI that stays quarantined shows Gatekeeper's dialog, nothing worse
        }
    }

    private static ProcessStartInfo Info(IReadOnlyList<string> argv)
    {
        var info = new ProcessStartInfo(argv[0])
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
        };
        foreach (var arg in argv.Skip(1))
        {
            info.ArgumentList.Add(arg);
        }
        return info;
    }

    private static Dictionary<string, string> Capture()
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (DictionaryEntry entry in System.Environment.GetEnvironmentVariables())
        {
            result[(string)entry.Key] = entry.Value as string ?? "";
        }
        return result;
    }

    private sealed class SystemLoginProcess : ILoginProcess
    {
        private readonly Process _process;

        public SystemLoginProcess(Process process, bool keepStdin)
        {
            _process = process;
            CanWrite = keepStdin;
            if (!keepStdin)
            {
                process.StandardInput.Close();
            }
        }

        public bool HasExited => _process.HasExited;

        public int? ExitCode => _process.HasExited ? _process.ExitCode : null;

        public bool CanWrite { get; }

        public async IAsyncEnumerable<string> ReadLinesAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
        {
            var lines = Channel.CreateUnbounded<string>();
            async Task Pump(StreamReader reader)
            {
                while (await reader.ReadLineAsync(ct).ConfigureAwait(false) is { } line)
                {
                    await lines.Writer.WriteAsync(line + "\n", ct).ConfigureAwait(false);
                }
            }
            var pumps = Task.WhenAll(Pump(_process.StandardOutput), Pump(_process.StandardError));
            _ = pumps.ContinueWith(t => lines.Writer.TryComplete(t.Exception), TaskScheduler.Default);
            await foreach (var line in lines.Reader.ReadAllAsync(ct).ConfigureAwait(false))
            {
                yield return line;
            }
        }

        public async ValueTask WriteAsync(string text, CancellationToken ct)
        {
            await _process.StandardInput.WriteAsync(text.AsMemory(), ct).ConfigureAwait(false);
            await _process.StandardInput.FlushAsync(ct).ConfigureAwait(false);
        }

        // The BCL has no SIGTERM: ending the tree is the closest, and a login holds nothing worth a goodbye.
        public void Terminate() => ProcessTree.Kill(_process);

        public void Kill() => ProcessTree.Kill(_process);

        public async Task<bool> WaitForExitAsync(TimeSpan timeout, CancellationToken ct)
        {
            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(timeout);
            try
            {
                await _process.WaitForExitAsync(limit.Token).ConfigureAwait(false);
                return true;
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                return false;
            }
        }
    }
}
