namespace D3sk.AgentCli.Runner;

/// <summary>What <see cref="ChildTurn.RunAsync"/> yields; the output parsers turn lines into agent events.</summary>
public abstract record ChildEvent;

/// <summary>One stdout line as raw bytes, newline included (the last line may have none).</summary>
public sealed record ChildLine(byte[] Bytes) : ChildEvent
{
    /// <summary>The line as UTF-8 text.</summary>
    public string Text => System.Text.Encoding.UTF8.GetString(Bytes);
}

/// <summary>The run failed; ends the stream, or precedes the final <see cref="ChildExited"/>.</summary>
/// <param name="Code">not_found, spawn_failed, child_died, timeout or read_failed.</param>
/// <param name="Message">A human-readable message (stderr's tail for a child that died).</param>
public sealed record ChildError(string Code, string Message) : ChildEvent;

/// <summary>The child is gone; the last event of a run that was not cancelled.</summary>
/// <param name="ExitCode">The exit code (0 for a child stopped after its turn ended).</param>
/// <param name="Stderr">The last 256 KiB of stderr, decoded leniently.</param>
/// <param name="StdoutAbandoned">stdout stayed open past the grace after the turn ended (a grandchild held it).</param>
public sealed record ChildExited(int ExitCode, string Stderr, bool StdoutAbandoned) : ChildEvent;
