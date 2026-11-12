namespace D3sk.AgentCli.Install;

/// <summary>
/// The end of an install, update or uninstall. A failure names the step that failed and why, so the
/// page can show "download failed: …" rather than a bare exit code.
/// </summary>
/// <param name="Ok">Whether every step succeeded.</param>
/// <param name="Step">The failed step: <c>plan</c>, <c>download</c>, <c>checksum</c>, <c>run</c>, <c>remove</c> or <c>verify</c>; empty on success.</param>
/// <param name="Message">Why it failed; empty on success.</param>
/// <param name="Output">The tail of what the steps printed.</param>
public sealed record InstallOutcome(bool Ok, string Step, string Message, string Output)
{
    /// <summary>Every step succeeded.</summary>
    public static InstallOutcome Succeeded(string output = "") => new(true, "", "", output);

    /// <summary>One step failed.</summary>
    public static InstallOutcome Failed(string step, string message, string output = "") => new(false, step, message, output);
}
