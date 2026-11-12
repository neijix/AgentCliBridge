namespace D3sk.AgentCli.Login;

/// <summary>A sign-in request that cannot be served; the message is safe to show.</summary>
public sealed class LoginException(string message) : InvalidOperationException(message);

/// <summary>The link a started sign-in waits on.</summary>
public sealed record LoginStarted(string Url, bool Running, string Output, bool NeedsCode, string UserCode);

/// <summary>A pasted code or key was handed to the waiting CLI.</summary>
public sealed record LoginSubmitted(bool Running, bool NeedsCode);

/// <summary>Whether a CLI is signed in now (null: unknown) and whether a sign-in is still waiting.</summary>
public sealed record LoginStatus(bool? SignedIn, bool Running, string Url, string Output, string Error, bool NeedsCode, string UserCode);

/// <summary>Timing knobs of <see cref="CliLogins"/>; tests shorten them.</summary>
public sealed record LoginTimings
{
    /// <summary>How long a started login is waited on for its link (it shows up within a second or two).</summary>
    public TimeSpan LinkWait { get; init; } = TimeSpan.FromSeconds(20);

    /// <summary>How long the owner has to approve a login in a browser.</summary>
    public TimeSpan LoginTimeout { get; init; } = TimeSpan.FromMinutes(10);

    /// <summary>How long a status or logout command may run.</summary>
    public TimeSpan StatusTimeout { get; init; } = TimeSpan.FromSeconds(20);

    /// <summary>How long a login told to stop has to exit before it is killed.</summary>
    public TimeSpan StopGrace { get; init; } = TimeSpan.FromSeconds(3);
}

/// <summary>
/// Signs an agent CLI in from a host's page: runs the CLI's own browser login with the browser
/// opening turned off, reads the link from its output and hands only that link back; the CLI,
/// still waiting on the host, finishes by itself. One sign-in at a time per CLI. Nothing here
/// logs a password, token or key: the CLI keeps its own login, and shown output is redacted.
/// </summary>
/// <remarks>The argv is built here from the binary the host discovered, never taken from the request.</remarks>
public sealed partial class CliLogins
{
    /// <summary>A pasted OAuth code, callback URL or API key, never a dump.</summary>
    public const int CodeMax = 2048;

    private readonly ILoginHost _host;
    private readonly TimeProvider _time;
    private readonly LoginTimings _timings;
    private readonly string _home;
    private readonly Dictionary<string, Login> _logins = new(StringComparer.Ordinal);
    private readonly Lock _gate = new();

    /// <summary>Creates the sign-in registry over <paramref name="host"/>.</summary>
    /// <param name="host">Starts the CLIs.</param>
    /// <param name="time">The clock the 10-minute limit is read from.</param>
    /// <param name="timings">Waits and limits; default the production values.</param>
    /// <param name="home">The user's home (where Copilot keeps its config); default the process's.</param>
    public CliLogins(ILoginHost host, TimeProvider? time = null, LoginTimings? timings = null, string? home = null)
    {
        _host = host;
        _time = time ?? TimeProvider.System;
        _timings = timings ?? new LoginTimings();
        _home = home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    }

    /// <summary>Starts <c>&lt;cli&gt; login</c> (or reuses the one still waiting) and returns its link.</summary>
    public async Task<LoginStarted> StartAsync(string command, string binary, CancellationToken ct = default)
    {
        var spec = LoginSpecs.For(command)
            ?? throw new LoginException($"This app cannot sign '{command}' in — run its own login on that computer");
        if (binary.Length == 0)
        {
            throw new LoginException($"No '{command}' binary on this machine");
        }
        _host.ClearQuarantine(binary);
        Login login;
        List<ILoginProcess> expired;
        lock (_gate)
        {
            expired = Expire();
            if (!_logins.TryGetValue(command, out login!) || !login.IsRunning)
            {
                login = Spawn(spec, binary);
                _logins[command] = login;
            }
        }
        await ReapAsync(expired).ConfigureAwait(false);
        await login.WaitForLinkAsync(spec.NeedsLink ? _timings.LinkWait : Min(_timings.LinkWait, TimeSpan.FromSeconds(1)), ct).ConfigureAwait(false);
        login.Complete(spec);
        if (login.Url.Length == 0 && spec.NeedsLink)
        {
            if (login.IsRunning)
            {
                await ReapAsync([login.Process]).ConfigureAwait(false);
            }
            var shown = LoginText.Tail(login.Text);
            throw new LoginException($"{command} login printed no sign-in link" + (shown.Length > 0 ? $": {shown}" : ""));
        }
        return new LoginStarted(login.Url, login.IsRunning, LoginText.Tail(login.Text), spec.ReadsCode, login.UserCode);
    }

    /// <summary>Hands a pasted sign-in code or API key to the CLI still waiting on stdin.</summary>
    public async Task<LoginSubmitted> SubmitAsync(string command, string code, CancellationToken ct = default)
    {
        var spec = LoginSpecs.For(command);
        if (spec is null || !spec.ReadsCode)
        {
            throw new LoginException($"{command} sign-in does not take a pasted code");
        }
        var pasted = code.Trim();
        if (pasted.Length == 0 || pasted.Contains('\n') || pasted.Contains('\r') || pasted.Length > CodeMax)
        {
            throw new LoginException("Paste the code from the sign-in page");
        }
        Login? login;
        List<ILoginProcess> expired;
        lock (_gate)
        {
            expired = Expire();
            _logins.TryGetValue(command, out login);
        }
        await ReapAsync(expired).ConfigureAwait(false);
        if (login is null || !login.IsRunning || !login.Process.CanWrite)
        {
            throw new LoginException("No sign-in is waiting — start it first");
        }
        try
        {
            await login.Process.WriteAsync(pasted + spec.CodeEol, ct).ConfigureAwait(false);
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException)
        {
            throw new LoginException("The sign-in ended before the code could be sent");
        }
        return new LoginSubmitted(login.IsRunning, NeedsCode: true);
    }

    /// <summary>Whether the CLI is signed in now, and whether a sign-in is still waiting.</summary>
    public async Task<LoginStatus> StatusAsync(string command, string binary, CancellationToken ct = default)
    {
        var spec = LoginSpecs.For(command) ?? throw new LoginException($"This app cannot sign '{command}' in");
        Login? login;
        List<ILoginProcess> expired;
        lock (_gate)
        {
            expired = Expire();
            _logins.TryGetValue(command, out login);
        }
        await ReapAsync(expired).ConfigureAwait(false);
        var (signedIn, error) = await SignedInAsync(spec, binary, ct).ConfigureAwait(false);
        var running = login?.IsRunning == true;
        if (signedIn != true && spec.ReadsOwnStatus && login is { IsRunning: false, Process.ExitCode: 0 })
        {
            signedIn = true; // the login just ended cleanly: trust it over a config not read back yet
        }
        return new LoginStatus(
            signedIn,
            running,
            running ? login!.Url : "",
            login is null ? "" : LoginText.Tail(login.Text),
            error,
            spec.ReadsCode && running && signedIn != true,
            running ? login!.UserCode : "");
    }

    /// <summary>Runs <c>&lt;cli&gt; logout</c> (a sign-in still waiting is ended first), then reports the status.</summary>
    public async Task<LoginStatus> LogoutAsync(string command, string binary, CancellationToken ct = default)
    {
        var spec = LoginSpecs.For(command)
            ?? throw new LoginException($"This app cannot sign '{command}' out — run its own logout on that computer");
        if (spec.LogoutHint.Length > 0)
        {
            throw new LoginException(spec.LogoutHint);
        }
        Login? waiting;
        lock (_gate)
        {
            _logins.TryGetValue(command, out waiting);
        }
        if (waiting is { IsRunning: true })
        {
            await ReapAsync([waiting.Process]).ConfigureAwait(false);
        }
        _host.ClearQuarantine(binary);
        LoginCommandResult done;
        try
        {
            done = await _host.RunAsync([binary, .. spec.Logout], _timings.StatusTimeout, ct).ConfigureAwait(false);
        }
        catch (Exception e) when (e is IOException or TimeoutException or System.ComponentModel.Win32Exception)
        {
            throw new LoginException($"{command} logout failed: {e.Message}");
        }
        var output = LoginText.Tail($"{done.Stdout}\n{done.Stderr}");
        if (done.ExitCode != 0)
        {
            throw new LoginException($"{command} logout failed" + (output.Length > 0 ? $": {output}" : ""));
        }
        return (await StatusAsync(command, binary, ct).ConfigureAwait(false)) with { Output = output };
    }

    /// <summary>Ends every sign-in still waiting (the app is closing).</summary>
    public async Task StopAllAsync()
    {
        List<ILoginProcess> running;
        lock (_gate)
        {
            running = [.. _logins.Values.Where(l => l.IsRunning).Select(l => l.Process)];
        }
        await ReapAsync(running).ConfigureAwait(false);
    }

    private async Task<(bool? SignedIn, string Error)> SignedInAsync(LoginSpec spec, string binary, CancellationToken ct)
    {
        try
        {
            if (spec.ReadsOwnStatus)
            {
                return (await CopilotSignIn.IsSignedInAsync(_host, _home, _timings.StatusTimeout, ct).ConfigureAwait(false), "");
            }
            _host.ClearQuarantine(binary);
            var done = await _host.RunAsync([binary, .. spec.Status], _timings.StatusTimeout, ct).ConfigureAwait(false);
            return (LoginText.ParseSignedIn(done.ExitCode, $"{done.Stdout}\n{done.Stderr}"), "");
        }
        catch (Exception e) when (e is IOException or TimeoutException or System.ComponentModel.Win32Exception)
        {
            return (null, e.Message.Length > 0 ? e.Message : e.GetType().Name);
        }
    }

    private Login Spawn(LoginSpec spec, string binary)
    {
        var process = _host.Start([binary, .. spec.Login], spec.Env, spec.ReadsCode);
        var login = new Login(process, _time.GetTimestamp());
        _ = Task.Run(() => login.ReadAsync(spec));
        return login;
    }

    /// <summary>Forgets every login the owner waited on too long (call under the gate); the caller reaps what it returns.</summary>
    private List<ILoginProcess> Expire()
    {
        var ended = new List<ILoginProcess>();
        foreach (var (command, login) in _logins.ToArray())
        {
            if (_time.GetElapsedTime(login.StartedAt) <= _timings.LoginTimeout)
            {
                continue;
            }
            if (login.IsRunning)
            {
                ended.Add(login.Process);
            }
            _logins.Remove(command);
        }
        return ended;
    }

    /// <summary>Ends login processes and collects them: terminate, wait a moment, kill, wait again (no zombie).</summary>
    private async Task ReapAsync(IEnumerable<ILoginProcess> processes)
    {
        foreach (var process in processes)
        {
            process.Terminate();
            if (!await process.WaitForExitAsync(_timings.StopGrace, CancellationToken.None).ConfigureAwait(false))
            {
                process.Kill();
                await process.WaitForExitAsync(_timings.StopGrace, CancellationToken.None).ConfigureAwait(false);
            }
        }
    }

    private static TimeSpan Min(TimeSpan a, TimeSpan b) => a < b ? a : b;
}
