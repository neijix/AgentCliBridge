namespace D3sk.AgentCli.Status;

/// <summary>
/// Gatekeeper's download mark on a CLI binary. Homebrew stamps <c>com.apple.quarantine</c> on a cask
/// upgrade, and launching the binary then raises the "Not Opened / Move to Trash" dialog, so the
/// version probe drops that one attribute first.
/// </summary>
public static class MacQuarantine
{
    /// <summary>The one extended attribute removed; every other stays.</summary>
    public const string Attribute = "com.apple.quarantine";

    private static readonly TimeSpan XattrTimeout = TimeSpan.FromSeconds(10);

    /// <summary>
    /// Drops the mark from <paramref name="path"/>'s real file. <c>false</c> when there was nothing
    /// to drop: off macOS, no path, no such file, the mark absent, or the removal failed (the
    /// caller's update still stands). <paramref name="xattr"/> runs <c>/usr/bin/xattr</c> with the
    /// given arguments and returns its exit code (a fake in tests).
    /// </summary>
    public static bool Clear(string path, bool? isMac = null, Func<IReadOnlyList<string>, int>? xattr = null)
    {
        if (!(isMac ?? OperatingSystem.IsMacOS()) || string.IsNullOrEmpty(path))
        {
            return false;
        }
        try
        {
            var target = File.ResolveLinkTarget(path, returnFinalTarget: true)?.FullName ?? Path.GetFullPath(path);
            if (!File.Exists(target))
            {
                return false;
            }
            var run = xattr ?? RunXattr;
            return run(["-p", Attribute, target]) == 0 && run(["-d", Attribute, target]) == 0;
        }
        catch (Exception ex) when (ex is IOException or System.ComponentModel.Win32Exception or TimeoutException or UnauthorizedAccessException or InvalidOperationException)
        {
            return false;
        }
    }

    private static int RunXattr(IReadOnlyList<string> args) =>
        ProbeProcess.RunAsync(["/usr/bin/xattr", .. args], XattrTimeout, CancellationToken.None).GetAwaiter().GetResult().ExitCode;
}
