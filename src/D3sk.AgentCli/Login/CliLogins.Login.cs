namespace D3sk.AgentCli.Login;

public sealed partial class CliLogins
{
    /// <summary>One sign-in process and what it has printed so far.</summary>
    private sealed class Login(ILoginProcess process, long startedAt)
    {
        private readonly Lock _lock = new();
        private readonly System.Text.StringBuilder _output = new();
        private readonly TaskCompletionSource _linkSeen = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private string _url = "";
        private string _userCode = "";

        public ILoginProcess Process { get; } = process;

        public long StartedAt { get; } = startedAt;

        public bool IsRunning => !Process.HasExited;

        public string Text
        {
            get
            {
                lock (_lock)
                {
                    return _output.ToString();
                }
            }
        }

        public string Url
        {
            get
            {
                lock (_lock)
                {
                    return _url;
                }
            }
        }

        public string UserCode
        {
            get
            {
                lock (_lock)
                {
                    return _userCode;
                }
            }
        }

        public async Task ReadAsync(LoginSpec spec)
        {
            try
            {
                await foreach (var line in Process.ReadLinesAsync(CancellationToken.None).ConfigureAwait(false))
                {
                    lock (_lock)
                    {
                        _output.Append(line);
                        if (_url.Length == 0)
                        {
                            _url = LoginText.Link(line, spec.Hosts);
                        }
                        if (_userCode.Length == 0)
                        {
                            _userCode = LoginText.UserCode(line);
                        }
                        if (_url.Length > 0 || !spec.NeedsLink)
                        {
                            _linkSeen.TrySetResult();
                        }
                    }
                }
            }
            catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException)
            {
                // the pipe closed under us: the login ended
            }
            finally
            {
                _linkSeen.TrySetResult(); // ended without a link: stop waiting for one
            }
        }

        public async Task WaitForLinkAsync(TimeSpan wait, CancellationToken ct)
        {
            try
            {
                await _linkSeen.Task.WaitAsync(wait, ct).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                // no link yet: the caller decides
            }
        }

        /// <summary>After the wait: the spec's fixed page when the CLI printed none, and a device code from the link.</summary>
        public void Complete(LoginSpec spec)
        {
            lock (_lock)
            {
                if (_url.Length == 0 && spec.Page.Length > 0)
                {
                    _url = LoginText.Link(spec.Page, spec.Hosts);
                }
                if (_userCode.Length == 0)
                {
                    _userCode = LoginText.UserCode(_output.ToString());
                    if (_userCode.Length == 0)
                    {
                        _userCode = LoginText.UserCode(_url);
                    }
                }
            }
        }
    }
}
