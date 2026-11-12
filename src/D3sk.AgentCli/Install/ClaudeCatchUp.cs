using System.Runtime.InteropServices;
using D3sk.AgentCli.Status;

namespace D3sk.AgentCli.Install;

/// <summary>What the catch-up did: code 0 with no note is nothing to do, 0 with a note is a replaced binary, 1 is an update that cannot be done.</summary>
/// <param name="Code">0 when the update the owner asked for is done or not needed, 1 when it cannot be done.</param>
/// <param name="Note">What to tell the owner; empty when nothing was done.</param>
public sealed record CatchUpResult(int Code, string Note);

/// <summary>
/// After <c>brew upgrade</c> the <c>claude-code@latest</c> cask can still sit behind npm, because Homebrew's formula lags
/// Anthropic's download. This installs the binary Anthropic publishes over the cask's file, but only when npm
/// advertises a newer version and Anthropic's download really is newer than what is installed, so an Update the
/// desk promised never ends in "already installed".
/// </summary>
/// <param name="release">Installs a published binary over the cask file.</param>
/// <param name="fetch">One GET of a release source, as <see cref="CliStatus.Fetch"/> reads it.</param>
public sealed class ClaudeCatchUp(ClaudeRelease release, Func<string, CancellationToken, Task<byte[]>> fetch)
{
    /// <summary>The catch-up for the <c>claude</c> at <paramref name="resolved"/>, installed at <paramref name="installed"/>, with <paramref name="npmLatest"/> advertised.</summary>
    public async Task<CatchUpResult> AfterUpgradeAsync(
        string resolved, string installed, string npmLatest, CancellationToken ct = default, string? os = null, string? arch = null)
    {
        if (!ClaudeRelease.IsLatestCaskBinary(resolved) || ReleaseSources.IsOutdated(installed, npmLatest) is not true)
        {
            return new CatchUpResult(0, "");
        }
        string published;
        try
        {
            published = await PublishedVersionAsync(ct).ConfigureAwait(false);
        }
        catch (InstallStepException ex)
        {
            return new CatchUpResult(1, $"Homebrew left Claude Code at {(installed.Length > 0 ? installed : "an unknown version")}. {ex.Message}");
        }
        if (ReleaseSources.IsOutdated(installed, published) is not true)
        {
            return new CatchUpResult(
                1,
                $"Homebrew's claude-code@latest cask is already at {installed}, and Anthropic's download is {(published.Length > 0 ? published : "not newer")}. "
                + $"npm advertises {npmLatest}, which is not a binary either of them is offering yet.");
        }
        var outcome = await release.InstallPublishedAsync(resolved, published, os ?? CurrentOs(), arch ?? CurrentArch(), ct).ConfigureAwait(false);
        return outcome.Ok ? new CatchUpResult(0, outcome.Output) : new CatchUpResult(1, outcome.Message);
    }

    /// <summary>The version Anthropic serves at <c>.../claude-code-releases/latest</c>.</summary>
    /// <exception cref="InstallStepException">The source did not answer or did not name a plain version.</exception>
    public async Task<string> PublishedVersionAsync(CancellationToken ct = default)
    {
        byte[] body;
        try
        {
            body = await fetch(ReleaseSources.ClaudeReleaseLatestUrl, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or IOException or InvalidOperationException or TaskCanceledException && !ct.IsCancellationRequested)
        {
            throw new InstallStepException("plan", $"could not read Anthropic's latest Claude version: {ex.Message}");
        }
        var version = ReleaseSources.ParseLatest("claude", body, "", isClaudeCask: true);
        return version.Length > 0 ? version : throw new InstallStepException("plan", "Anthropic's latest release did not name a version");
    }

    private static string CurrentOs() => OperatingSystem.IsMacOS() ? "darwin" : OperatingSystem.IsLinux() ? "linux" : "windows";

    private static string CurrentArch() => RuntimeInformation.OSArchitecture == Architecture.Arm64 ? "arm64" : "x64";
}
