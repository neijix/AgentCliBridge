using System.ComponentModel;
using System.Diagnostics;

namespace D3sk.AgentCli.Runner;

/// <summary>Kills a CLI together with everything it started.</summary>
internal static class ProcessTree
{
    /// <summary>
    /// Kills <paramref name="process"/> and its descendants (agents spawn children that inherit
    /// our pipes; killing only the parent leaves orphans holding them). Safe on a process that
    /// already exited.
    /// </summary>
    public static void Kill(Process process)
    {
        try
        {
            process.Kill(entireProcessTree: true);
        }
        catch (Exception e) when (e is InvalidOperationException or Win32Exception or NotSupportedException or AggregateException)
        {
            // already gone, or access denied on a descendant that exited meanwhile
        }
    }
}
