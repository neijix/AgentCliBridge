namespace D3sk.AgentCli.Install;

/// <summary>
/// Carries out a <see cref="CliPlan"/>: downloads and checks its script, runs each command in order
/// and stops at the first failure, saying which step failed and why. Nothing is run through a shell.
/// </summary>
public sealed class CliInstaller(IProcessRunner runner, ScriptDownloader downloader)
{
    /// <summary>How long one command may run: <c>brew upgrade</c> refreshes taps, an npm install downloads.</summary>
    public static TimeSpan StepTimeout { get; } = TimeSpan.FromMinutes(10);

    /// <summary>Run <paramref name="plan"/> from start to end.</summary>
    public async Task<InstallOutcome> RunAsync(CliPlan plan, CancellationToken ct)
    {
        if (!plan.Runnable)
        {
            return InstallOutcome.Failed("plan", plan.Hint.Length > 0 ? $"this host cannot do it: {plan.Hint}" : "there is nothing to run");
        }
        if (plan.Remove is { } remove)
        {
            return NativeInstalls.Remove(remove);
        }
        string? folder = null;
        try
        {
            IReadOnlyList<string> first = plan.Argv;
            if (plan.Script is { } script)
            {
                folder = Directory.CreateTempSubdirectory("d3sk-install-").FullName;
                var file = await downloader.FetchAsync(script, folder, ct).ConfigureAwait(false);
                first = [.. script.Interpreter, file];
            }
            var output = new List<string>();
            var steps = new List<IReadOnlyList<string>> { first };
            steps.AddRange(plan.Then);
            for (var i = 0; i < steps.Count; i++)
            {
                var result = await runner.RunAsync(steps[i], StepTimeout, ct).ConfigureAwait(false);
                output.Add(result.Output);
                if (result.ExitCode != 0)
                {
                    var which = steps.Count > 1 ? $" (step {i + 1} of {steps.Count})" : "";
                    var program = Path.GetFileName(steps[i][0]);
                    var why = result.ExitCode < 0 ? result.Output : $"exited with {result.ExitCode}";
                    return InstallOutcome.Failed("run", $"{program} failed{which}: {why}", string.Join('\n', output).Trim());
                }
            }
            return InstallOutcome.Succeeded(string.Join('\n', output).Trim());
        }
        catch (InstallStepException ex)
        {
            return InstallOutcome.Failed(ex.Step, ex.Message);
        }
        finally
        {
            if (folder is not null)
            {
                try
                {
                    Directory.Delete(folder, recursive: true);
                }
                catch (IOException)
                {
                    // A temp folder left behind is not an install failure.
                }
            }
        }
    }
}
