using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;
using D3sk.AgentCli.Runner;

namespace D3sk.AgentCli.Host;

/// <summary>
/// One live Claude turn's plumbing: the host's <see cref="TurnInput"/> bound to the child's stdin, and the
/// <see cref="LiveLines"/> the parser reads the control lines with. The runner binds the stdin once the CLI has
/// started: the prompt is written from the runner's started hook, and what is said before then waits in the input.
/// </summary>
internal sealed class LiveTurn : IDisposable
{

    private LiveTurn(TurnInput input, ChildInput stdin)
    {
        Input = input;
        Stdin = stdin;
        Lines = new LiveLines(input, payload => stdin.WriteLine(payload.ToJsonString()));
    }

    /// <summary>The host's input channel.</summary>
    internal TurnInput Input { get; }

    /// <summary>The child's stdin, bound by the runner at start.</summary>
    internal ChildInput Stdin { get; }

    /// <summary>The parser's reader of control lines.</summary>
    internal LiveLines Lines { get; }

    /// <summary>The live plumbing for a CLI that takes input mid-turn (Claude); a turn that cannot gets its input closed and null.</summary>
    internal static LiveTurn? For(TurnInput? input, string flavor)
    {
        if (input is null)
        {
            return null;
        }
        if (!SupportsLiveInput(flavor))
        {
            Close(input); // this CLI cannot take input mid-turn: Say and Answer return false
            return null;
        }
        return new LiveTurn(input, new ChildInput());
    }

    /// <summary>Only Claude Code takes messages and approvals while a turn runs.</summary>
    internal static bool SupportsLiveInput(string flavor) => flavor == "claude";

    /// <summary>Ends the input channel: nothing more is accepted and no approval stays pending.</summary>
    internal static void Close(TurnInput input) => input.Close();

    /// <summary>Writes the prompt (then what was said early) as soon as the runner has bound the child's stdin.</summary>
    internal void Start(string prompt) => Stdin.WhenBound(() => Input.Start(Stdin, prompt));

    /// <summary>The turn's stdin closes: the CLI exits after its result.</summary>
    internal void CloseStdin() => Stdin.Close();

    /// <summary>Closes stdin and the input channel; safe to call again.</summary>
    internal void End()
    {
        Stdin.Close();
        Close(Input);
    }

    /// <inheritdoc />
    public void Dispose() => End();
}
