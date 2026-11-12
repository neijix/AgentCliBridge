using System.Net;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;

namespace D3sk.AgentCli.Local;

/// <summary>
/// A text chat with a model D3SKMODEL serves: no CLI, no tools, one request, run headless. It talks only
/// over a keyed, user-only endpoint (<see cref="MlxLink"/>); a server that is not upgraded gives
/// <see cref="LocalServiceState.NeedsUpdateCode"/>, never a retry over plain HTTP. The model is the one the
/// server has loaded: loading and starting it belong to D3SKMODEL itself.
/// </summary>
public static class MlxChat
{
    private const string Code = "mlx_failed";
    /// <summary>The <see cref="Notice.Kind"/> of the note shown while the server loads the model.</summary>
    public const string LoadingKind = "loading";

    private const int MaxTokens = 8192;

    /// <summary>The context window of the models this desk lists, for the context meter.</summary>
    public const int ContextWindow = 32_768;

    /// <summary>
    /// Streams one reply as <see cref="ThinkingDelta"/>s and <see cref="TextDelta"/>s, after one display-only
    /// <see cref="Notice"/> ("Loading {model}…") when the server is slow to answer. A failure is a
    /// <see cref="StreamError"/> then <c>Completed(1)</c>; cancelling ends the stream without either.
    /// </summary>
    /// <param name="model">The model id; empty takes the first downloaded one.</param>
    /// <param name="prompt">The user's message.</param>
    /// <param name="cwd">The project folder, named to the model.</param>
    /// <param name="projectName">The project's name, else the folder's.</param>
    /// <param name="options">Where MLX is and where its key comes from.</param>
    /// <param name="installed">The downloaded model ids; null lists the cache.</param>
    /// <param name="cancellationToken">Closes the response of a cancelled turn.</param>
    public static async IAsyncEnumerable<StreamEvent> StreamTurnAsync(
        string model,
        string prompt,
        string cwd,
        string? projectName,
        MlxOptions options,
        IReadOnlyList<string>? installed = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var available = installed ?? MlxModels.Installed(options.ModelCache);
        var chosen = model.Length > 0 ? model : available.FirstOrDefault() ?? "";
        if (!available.Contains(chosen))
        {
            yield return new StreamError($"{(chosen.Length > 0 ? MlxModels.Short(chosen) : "That model")} is not downloaded on this computer.", Code);
            yield return new Completed(1);
            yield break;
        }

        using var link = await MlxLink.ConnectAsync(options, cancellationToken).ConfigureAwait(false);
        if (!link.State.IsReady)
        {
            yield return new StreamError(link.State.Detail, CodeOf(link.State));
            yield return new Completed(1);
            yield break;
        }

        var system = MlxModels.SystemText(cwd, projectName, options.ReplyRules);
        await using var replies = ReplyAsync(link, chosen, prompt, system, options, cancellationToken).GetAsyncEnumerator(cancellationToken);
        var spoke = false;
        string? failure = null;
        var noticed = false;
        while (true)
        {
            var next = replies.MoveNextAsync().AsTask();
            if (!spoke && !noticed)
            {
                noticed = true;
                using var wait = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                var late = Task.Delay(options.LoadNoticeDelay, wait.Token);
                var first = await Task.WhenAny(next, late).ConfigureAwait(false);
                await wait.CancelAsync().ConfigureAwait(false);
                if (first == late && !next.IsCompleted && !cancellationToken.IsCancellationRequested)
                {
                    yield return new Notice($"Loading {MlxModels.Short(chosen)}…", LoadingKind);
                }
            }

            bool more;
            try
            {
                more = await next.ConfigureAwait(false);
            }
            catch (MlxException e)
            {
                failure = e.Message;
                break;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                yield break;
            }

            if (!more)
            {
                break;
            }

            var (text, thinking) = replies.Current;
            if (thinking.Length > 0)
            {
                spoke = true;
                yield return new ThinkingDelta(thinking);
            }

            if (text.Length > 0)
            {
                spoke = true;
                yield return new TextDelta(text);
            }
        }

        if (failure is null && !spoke)
        {
            failure = "The local model returned nothing.";
        }

        if (failure is not null)
        {
            yield return new StreamError(failure, Code);
            yield return new Completed(1);
            yield break;
        }

        yield return new Completed(0);
    }

    private static string CodeOf(LocalServiceState state) => state.Status switch
    {
        LocalServiceStatus.NeedsUpdate => LocalServiceState.NeedsUpdateCode,
        LocalServiceStatus.NoKey => LocalServiceState.NoKeyCode,
        _ => Code,
    };

    private static async IAsyncEnumerable<(string Text, string Thinking)> ReplyAsync(
        MlxLink link,
        string model,
        string prompt,
        string system,
        MlxOptions options,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        var body = new JsonObject
        {
            ["model"] = model,
            ["messages"] = new JsonArray(
                new JsonObject { ["role"] = "system", ["content"] = system },
                new JsonObject { ["role"] = "user", ["content"] = prompt }),
            ["max_tokens"] = MaxTokens,
            ["temperature"] = 0.2,
            ["stream"] = true,
        };
        using var request = new HttpRequestMessage(HttpMethod.Post, link.Url("/v1/chat/completions"))
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        request.Headers.Accept.ParseAdd("text/event-stream");
        using var idle = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        idle.CancelAfter(options.StreamIdleTimeout);
        HttpResponseMessage response;
        try
        {
            response = await link.SendAsync(request, idle.Token).ConfigureAwait(false);
        }
        catch (Exception e) when (e is HttpRequestException or IOException or OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            throw new MlxException($"Could not reach {MlxOptions.Name} on this computer.");
        }

        using (response)
        {
            if ((int)response.StatusCode >= 400)
            {
                throw await ErrorAsync(response, idle.Token).ConfigureAwait(false);
            }

            await foreach (var pair in ReadBodyAsync(response, idle, options, cancellationToken).ConfigureAwait(false))
            {
                yield return pair;
            }
        }
    }

    private static async IAsyncEnumerable<(string Text, string Thinking)> ReadBodyAsync(
        HttpResponseMessage response,
        CancellationTokenSource idle,
        MlxOptions options,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        await using var stream = await response.Content.ReadAsStreamAsync(idle.Token).ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        var first = true;
        while (true)
        {
            idle.CancelAfter(options.StreamIdleTimeout);
            string? line;
            try
            {
                line = await reader.ReadLineAsync(idle.Token).ConfigureAwait(false);
            }
            catch (Exception e) when (e is IOException or HttpRequestException or OperationCanceledException && !cancellationToken.IsCancellationRequested)
            {
                throw new MlxException($"{MlxOptions.Name} stopped answering.");
            }

            if (line is null)
            {
                yield break;
            }

            if (first)
            {
                first = false;
                var stripped = line.TrimStart();
                if (stripped.StartsWith('{') && !stripped.StartsWith("data:", StringComparison.Ordinal))
                {
                    var text = MlxSse.UnaryText(line + "\n" + await reader.ReadToEndAsync(idle.Token).ConfigureAwait(false), MlxOptions.Name);
                    if (text.Length > 0)
                    {
                        yield return (text, "");
                    }

                    yield break;
                }
            }

            if (MlxSse.DeltaPair(line) is { } pair)
            {
                yield return pair;
            }
        }
    }

    private static async Task<MlxException> ErrorAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.StatusCode == HttpStatusCode.Unauthorized)
        {
            return new MlxException($"{MlxOptions.Name} refused the key. Run `d3skmodel setup`.");
        }

        var detail = MlxSse.ErrorDetail(await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false));

        return new MlxException(detail ?? $"{MlxOptions.Name} returned HTTP {(int)response.StatusCode}.");
    }
}
