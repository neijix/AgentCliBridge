using D3sk.AgentCli.Accounts;
using D3sk.AgentCli.ChildEnv;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;
using D3sk.AgentCli.Output.Copilot;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Security;
using D3sk.AgentCli.Specs.OpenCode;

namespace D3sk.AgentCli.Host;

/// <summary>
/// What a turn is started with, or why it cannot be: the runner command, its parser, Copilot's side channel, the
/// wrapper that guards the host stream and the live-input plumbing.
/// </summary>
internal sealed record AgentLaunch(
    ChildCommand? Command, StreamError? Refusal, IOutputParser? Parser, CopilotStatus? Status, TurnDeadline Deadline,
    TurnGuard? Watch = null, LiveTurn? Live = null)
{
    private const string BackgroundWaitVariable = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS";
    private static readonly string[] BridgeTokens = ["BRIDGE_TOKEN", "BRIDGE_OWNER_TOKEN"];

    /// <summary>Resolves the binary, builds argv and environment, and picks the parser. Throws when the host passed no environment.</summary>
    internal static AgentLaunch Prepare(AgentTurnRequest request)
    {
        if (request.Env is null || request.Env.Count == 0) throw new MissingChildEnvironmentException(); // before anything is armed
        var flavor = AgentRegistry.FlavorFor(request.Command);
        var armed = TurnArming.Arm(request, flavor);
        var launch = Launch(armed.Request, flavor, armed);
        if (launch.Command is null)
        {
            armed.Live?.Dispose(); // nothing will run: the host's input is closed
        }
        return launch;
    }

    private static AgentLaunch Launch(AgentTurnRequest r, string flavor, ArmedTurn armed)
    {
        var deadline = r.Run?.Deadline ?? new TurnDeadline(TurnDeadline.DefaultGrace);
        var spec = AgentRegistry.Find(r.Command);
        var env = TurnEnvironment(r, flavor);
        var binary = r.Binary ?? (r.BinaryResolver ?? (c => AgentRegistry.ResolveBinary(c)))(r.Command);
        if (BinaryRefusal(r, spec, flavor, binary) is { } refusal)
        {
            return new AgentLaunch(null, refusal, null, null, deadline);
        }

        var live = armed.Live;
        var prompt = ComposePrompt(flavor, r);
        var (plan, onStdin, launchRefusal) = PlanLaunch(r, flavor, binary!, prompt, env, live is not null);
        if (launchRefusal is not null)
        {
            return new AgentLaunch(null, launchRefusal, null, null, deadline);
        }
        foreach (var (key, value) in plan.EnvOverlay) env[key] = value; // what the launcher itself would have set

        var command = new ChildCommand
        {
            FileName = plan.Argv[0],
            Arguments = [.. plan.Argv.Skip(1)],
            WorkingDirectory = r.Cwd,
            Environment = env,
            StdinText = onStdin ? prompt : null,
            LiveInput = live?.Stdin,
        };
        var status = flavor == "copilot" ? new CopilotStatus() : null;
        return new AgentLaunch(command, null, AgentParsers.For(flavor, r.Activity, deadline, status, live), status, deadline, armed.Watch, live);
    }

    /// <summary>Why the turn cannot start on <paramref name="binary"/>: not found, or Cursor's name on Grok's binary; null when it can.</summary>
    private static StreamError? BinaryRefusal(AgentTurnRequest r, AgentSpec? spec, string flavor, string? binary)
    {
        if (string.IsNullOrEmpty(binary))
        {
            var hint = spec?.InstallHint is { Length: > 0 } h ? h : $"Install `{r.Command}` and ensure it is on PATH.";
            return new StreamError($"CLI agent binary not found: {r.Command}. {hint}", "not_found");
        }
        if (flavor == "cursor" && AgentDiscovery.IsCursorGrokCollision(new AgentInfo(r.Command, spec?.Name ?? r.Command, binary, flavor, [], true, "")))
        {
            return new StreamError(AgentDiscovery.CollisionRefusal(spec?.Name ?? "Cursor Agent", binary), "cli_collision");
        }
        return null;
    }

    /// <summary>The launch plan, with the prompt moved to stdin when the command line would be too long; or why it cannot run.</summary>
    private static (LaunchPlan Plan, bool OnStdin, StreamError? Refusal) PlanLaunch(
        AgentTurnRequest r, string flavor, string binary, string prompt, Dictionary<string, string> env, bool live)
    {
        var canStdin = flavor is "claude" or "grok" && !live; // a live turn writes the prompt itself
        var onStdin = canStdin && WindowsLaunch.IsTooLong(Argv(flavor, binary, prompt, r, false, live));
        LaunchPlan plan;
        try
        {
            plan = WindowsLaunch.DirectLaunch(Argv(flavor, binary, prompt, r, onStdin, live), env);
            if (canStdin && !onStdin && WindowsLaunch.IsTooLong(plan.Argv))
            {
                onStdin = true; // only too long once the launcher's program was added
                plan = WindowsLaunch.DirectLaunch(Argv(flavor, binary, prompt, r, true, live), env);
            }
        }
        catch (UnsafeLauncherException e)
        {
            return (default!, false, new StreamError(e.Message, "spawn_failed"));
        }
        return WindowsLaunch.IsTooLong(plan.Argv)
            ? (plan, onStdin, new StreamError(TooLongMessage(r.Command, plan.Argv), "prompt_too_long"))
            : (plan, onStdin, null);
    }

    private static Dictionary<string, string> TurnEnvironment(AgentTurnRequest r, string flavor)
    {
        if (r.Env is null || r.Env.Count == 0) throw new MissingChildEnvironmentException();
        var allowlist = r.Env.Where(p => !BridgeTokens.Contains(p.Key, StringComparer.OrdinalIgnoreCase))
            .ToDictionary(p => p.Key, p => p.Value);
        var hostChoseWait = r.Env.ContainsKey(BackgroundWaitVariable) || (r.ExtraEnv?.ContainsKey(BackgroundWaitVariable) ?? false);
        var built = ChildEnvironment.Build(allowlist, r.ShimFolder, flavor == "claude" ? ChildEnvironment.TranscriptKillerPrefixes : null);
        var env = new Dictionary<string, string>(built, OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
        foreach (var (key, value) in r.ExtraEnv ?? new Dictionary<string, string>()) env[key] = value;
        if (r.Accounts is not null && r.Cwd is not null)
        {
            foreach (var (key, value) in r.Accounts.TurnEnv(r.Command, r.Cwd)) env[key] = value;
        }
        if (flavor == "claude" && !hostChoseWait)
        {
            // `claude -p` stops background subagents 10 minutes after the last turn; 0 makes it wait for them.
            env[BackgroundWaitVariable] = "0";
        }
        if (flavor == "opencode")
        {
            if (OpenCodeEnvironment.ConfigContent(r.Model, env.GetValueOrDefault(OpenCodeEnvironment.ConfigVariable)) is { } content)
            {
                env[OpenCodeEnvironment.ConfigVariable] = content;
            }
            OpenCodeEnvironment.Directory(env, r.Cwd);
        }
        return env;
    }

    private static string ComposePrompt(string flavor, AgentTurnRequest r) => flavor switch
    {
        "claude" => r.Prompt, // --append-system-prompt carries the system text
        "gemini" => Specs.Gemini.GeminiArgv.ComposePrompt(r.Prompt, r.SystemText, r.ResumeId),
        _ => Specs.Cursor.CursorArgv.ComposePrompt(r.Prompt, r.SystemText, r.ResumeId), // the rule every other CLI shares
    };

    private static List<string> Argv(string flavor, string binary, string prompt, AgentTurnRequest r, bool onStdin, bool live) => flavor switch
    {
        "cursor" => Specs.Cursor.CursorArgv.Build(new() { Binary = binary, Prompt = prompt, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode }),
        "antigravity" => Specs.Agy.AgyArgv.Build(new() { Binary = binary, Prompt = prompt, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode, Cwd = r.Cwd }),
        "gemini" => Specs.Gemini.GeminiArgv.Build(new() { Binary = binary, Prompt = prompt, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode }),
        "grok" => Specs.Grok.GrokArgv.Build(new() { Binary = binary, Prompt = prompt, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode, PromptOnStdin = onStdin }),
        "copilot" => Specs.Copilot.CopilotArgv.Build(new() { Binary = binary, Prompt = prompt, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode, Effort = r.Effort }),
        "opencode" => Specs.OpenCode.OpenCodeArgv.Build(new() { Binary = binary, Prompt = prompt, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model, PermissionMode = r.PermissionMode }),
        _ => Specs.Claude.ClaudeArgv.Build(new()
        {
            Binary = binary, Prompt = prompt, SystemText = r.SystemText, ResumeId = r.ResumeId, CliArgs = r.CliArgs, Model = r.Model,
            PermissionMode = r.PermissionMode, PromptOnStdin = onStdin, AllowedTools = r.AllowedTools, AllowSudo = r.AllowSudo,
            Effort = r.Effort, Ultracode = r.Ultracode, BridgeHome = r.BridgeHome, LiveInput = live,
        }),
    };

    private static string TooLongMessage(string command, IReadOnlyList<string> argv)
    {
        var length = WindowsLaunch.CommandLineLength(argv);
        return length == 0
            ? $"This turn is too long for the command line that starts {command} (one argument reaches the {WindowsLaunch.LinuxArgLimit:N0}-byte limit). Shorten the message, or continue in a new chat."
            : $"This turn is too long for the Windows command line that starts {command} ({length:N0} characters; the limit is {WindowsLaunch.CommandLineLimit:N0}). Shorten the message, or continue in a new chat.";
    }
}
