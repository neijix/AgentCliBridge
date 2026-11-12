using System.Text.Json.Nodes;
using D3sk.AgentCli.Runner;
using D3sk.AgentCli.Specs.Claude;

namespace D3sk.AgentCli.Control;

/// <summary>
/// Answers a running turn's tool approvals and adds messages to it (Claude Code only).
/// </summary>
/// <remarks>
/// Create one per turn and call <see cref="Say"/> / <see cref="Answer"/> from any thread. The
/// CLI is started with <c>--input-format stream-json --permission-prompt-tool stdio
/// --replay-user-messages</c> and takes the prompt on stdin; it asks before a gated tool with a
/// <c>can_use_tool</c> control request, takes a message written to stdin at its next step and
/// echoes it back as a replay, switches its permission mode on <c>set_permission_mode</c>, ends
/// each turn with a <c>result</c> and exits once stdin is closed. <see cref="Say"/> only hands a
/// message over: <see cref="LiveLines"/> yields <c>InputAccepted</c> once the CLI took it. Every
/// method returns false when the turn cannot take the input (the turn ended, an approval that is
/// unknown or already answered).
/// </remarks>
public sealed class TurnInput
{
    /// <summary>What the model reads when the user denies a call without a reason.</summary>
    public const string DeniedMessage = "The user denied this tool call.";

    private readonly object _gate = new();
    private readonly List<string> _backlog = []; // said before the CLI was started
    private readonly Dictionary<string, JsonNode> _approvals = []; // request id -> the tool input it asks about
    private readonly Dictionary<string, string> _modeRequests = []; // our control request id -> the mode asked for
    private Func<JsonObject, bool>? _write;
    private bool _closed;
    private int _untaken; // written to the CLI, not echoed back yet
    private string? _earlyMode; // asked for before the CLI was started
    private int _modeCount;

    /// <summary>Whether the turn still takes input; false once its <c>result</c> arrived with nothing left on the way.</summary>
    public bool IsOpen
    {
        get
        {
            lock (_gate)
            {
                return !_closed;
            }
        }
    }

    /// <summary>Adds a message to the running turn; before the CLI starts it waits and follows the prompt.</summary>
    public bool Say(string text)
    {
        lock (_gate)
        {
            if (_closed || string.IsNullOrEmpty(text))
            {
                return false;
            }
            if (_write is null)
            {
                _backlog.Add(text);
                return true;
            }
            if (!_write(UserMessage(text)))
            {
                return false;
            }
            _untaken++;
            return true;
        }
    }

    /// <summary>
    /// Allows or denies one pending tool call. An allowed call runs with the input the CLI asked
    /// about, never an edited one, and no permission rule or mode change is ever sent: an approval
    /// covers this call only.
    /// </summary>
    public bool Answer(string requestId, bool allow, string message = "")
    {
        lock (_gate)
        {
            if (_write is null || !_approvals.Remove(requestId, out var toolInput))
            {
                return false;
            }
            var decision = allow
                ? new JsonObject { ["behavior"] = "allow", ["updatedInput"] = toolInput }
                : new JsonObject { ["behavior"] = "deny", ["message"] = message.Trim() is { Length: > 0 } reason ? reason : DeniedMessage };
            return _write(Response(requestId, decision));
        }
    }

    /// <summary>
    /// Answers one pending AskUserQuestion call: allows it with an <c>updatedInput</c> carrying the
    /// chosen <paramref name="answers"/> (keyed by the question text; a value is one option label, a
    /// list of labels for a multi-select, or free text) and an optional global
    /// <paramref name="response"/>. It only substitutes input for AskUserQuestion, a call whose asked
    /// input is a <c>{"questions": [...]}</c> object, so a gated file or shell tool can never run with
    /// an edited input through this path: such a call is left pending and false is returned.
    /// </summary>
    public bool AnswerQuestion(string requestId, IReadOnlyDictionary<string, JsonNode?>? answers, string response = "")
    {
        lock (_gate)
        {
            if (_write is null
                || !_approvals.TryGetValue(requestId, out var asked)
                || asked is not JsonObject toolInput
                || !toolInput.ContainsKey("questions"))
            {
                return false;
            }
            _approvals.Remove(requestId);

            var updated = new JsonObject { ["questions"] = toolInput["questions"]?.DeepClone() };
            if (toolInput["metadata"] is JsonObject metadata)
            {
                updated["metadata"] = metadata.DeepClone();
            }
            var chosen = new JsonObject();
            foreach (var (question, value) in answers ?? new Dictionary<string, JsonNode?>())
            {
                if (!IsEmptyAnswer(value))
                {
                    chosen[question] = value!.DeepClone();
                }
            }
            if (chosen.Count > 0)
            {
                updated["answers"] = chosen;
            }
            if (response?.Trim() is { Length: > 0 } text)
            {
                updated["response"] = text;
            }
            return _write(Response(requestId, new JsonObject { ["behavior"] = "allow", ["updatedInput"] = updated }));
        }
    }

    /// <summary>
    /// Switches the running turn to another permission mode from its next tool call on. Only hands
    /// the request over: <see cref="LiveLines"/> yields <c>ModeChanged</c> once the CLI took it (or
    /// refused it). The host clamps <paramref name="mode"/> to what it allows before calling this;
    /// <c>bypassPermissions</c> also needs the CLI started with
    /// <c>--allow-dangerously-skip-permissions</c>. False for an unknown mode or a closed turn.
    /// </summary>
    public bool SetPermissionMode(string mode)
    {
        lock (_gate)
        {
            if (_closed || !ClaudeArgv.PermissionModes.Contains(mode))
            {
                return false;
            }
            if (_write is null)
            {
                _earlyMode = mode;
                return true;
            }
            return RequestMode(mode);
        }
    }

    /// <summary>
    /// Starts the turn on a live child: writes the prompt, then everything said before the CLI
    /// started, then a permission mode asked for early.
    /// </summary>
    public bool Start(ChildInput input, string prompt)
    {
        ArgumentNullException.ThrowIfNull(input);
        return Bind(payload => input.WriteLine(payload.ToJsonString()), prompt);
    }

    /// <summary>Like <see cref="Start"/> over any writer; the writer returns false when the line cannot be delivered.</summary>
    public bool Bind(Func<JsonObject, bool> write, string prompt)
    {
        ArgumentNullException.ThrowIfNull(write);
        lock (_gate)
        {
            var wrote = write(UserMessage(prompt));
            _write = write;
            var backlog = _backlog.ToArray();
            _backlog.Clear();
            foreach (var text in backlog)
            {
                if (write(UserMessage(text)))
                {
                    _untaken++;
                }
            }
            if (_earlyMode is { } mode)
            {
                RequestMode(mode);
                _earlyMode = null;
            }
            return wrote;
        }
    }

    // runner side: called by LiveLines as the CLI's lines arrive

    /// <summary>The CLI asked before a gated tool: remembers the input it asked about, so an allow can only carry that.</summary>
    public void Asked(string requestId, JsonNode toolInput)
    {
        lock (_gate)
        {
            _approvals[requestId] = toolInput.DeepClone();
        }
    }

    /// <summary>The CLI withdrew a request: it can no longer be answered.</summary>
    public void Withdrawn(string requestId)
    {
        lock (_gate)
        {
            _approvals.Remove(requestId);
        }
    }

    /// <summary>The CLI echoed back a message added with <see cref="Say"/>.</summary>
    public void TookMessage()
    {
        lock (_gate)
        {
            _untaken = Math.Max(0, _untaken - 1);
        }
    }

    /// <summary>The mode one of our permission-mode requests asked for; null when the id is not ours.</summary>
    public string? ModeAnswered(string requestId)
    {
        lock (_gate)
        {
            return _modeRequests.Remove(requestId, out var mode) ? mode : null;
        }
    }

    /// <summary>A <c>result</c> arrived: true (and no more input) unless a message is still on its way.</summary>
    public bool TurnEnded()
    {
        lock (_gate)
        {
            if (_untaken > 0)
            {
                return false;
            }
            CloseLocked();
            return true;
        }
    }

    /// <summary>Ends the input now: nothing more is accepted and no approval stays pending, whatever is still on its way. Safe to call again.</summary>
    public void Close()
    {
        lock (_gate)
        {
            _untaken = 0; // a message still on its way will not be echoed back now
            CloseLocked();
        }
    }

    private void CloseLocked()
    {
        _closed = true;
        _approvals.Clear();
        _backlog.Clear();
        _earlyMode = null;
        _modeRequests.Clear();
    }

    private bool RequestMode(string mode)
    {
        _modeCount++;
        var requestId = $"d3sk-mode-{_modeCount}";
        var request = new JsonObject
        {
            ["type"] = "control_request",
            ["request_id"] = requestId,
            ["request"] = new JsonObject { ["subtype"] = "set_permission_mode", ["mode"] = mode },
        };
        if (!_write!(request))
        {
            return false;
        }
        _modeRequests[requestId] = mode;
        return true;
    }

    private static bool IsEmptyAnswer(JsonNode? value) =>
        value is null || value is JsonArray { Count: 0 } || (value is JsonValue v && v.TryGetValue<string>(out var s) && s.Length == 0);

    private static JsonObject UserMessage(string text) => new()
    {
        ["type"] = "user",
        ["session_id"] = "",
        ["parent_tool_use_id"] = null,
        ["message"] = new JsonObject { ["role"] = "user", ["content"] = text },
    };

    private static JsonObject Response(string requestId, JsonObject decision) => new()
    {
        ["type"] = "control_response",
        ["response"] = new JsonObject { ["subtype"] = "success", ["request_id"] = requestId, ["response"] = decision },
    };
}
